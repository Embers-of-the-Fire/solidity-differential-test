"""Multi-version solang compatibility probe (T2.2).

Per solang version: compile a smoke contract (the counter example covers
compile + deploy + steps), running the full oracle with ORACLE_SOLANG_BIN
pointed at that version's binary. Versions whose WASM the current
substrate-contracts-node rejects are recorded "incompatible" (matching-era
node pinning is out of scope v1 — a known limitation for the threats
section).

Output: agent/data/version_matrix.json — one record per version:

    {"version": "0.3.4", "binary": "/nix/store/.../bin/solang",
     "compile_ok": true, "deploy_evm": "success", "deploy_polkadot": "success",
     "verdict": "PASS", "compatible": true, "note": "..."}

Usage (from the repo root, inside the devshell):

    uv run --package solidity-diff-agent python agent/tools/solang_compat.py \
        --bin 0.3.0="$(nix build .#solang_0_3_0 --no-link --print-out-paths)/bin/solang" ...
    (with no --bin given, versions are resolved via `nix build` automatically)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

VERSIONS = ["0.3.0", "0.3.1", "0.3.2", "0.3.3", "0.3.4", "0.3.5"]

SMOKE_SPEC = {
    "name": "version-compat-probe",
    "solidity": (
        "pragma solidity >=0.8.0;\n"
        "contract counter {\n"
        "    uint256 public count;\n"
        "    function inc(uint256 by) external { count += by; }\n"
        "}\n"
    ),
    "contract": "counter",
    "steps": [
        {"action": "call", "function": "inc", "args": [5]},
        {"action": "query", "function": "count"},
    ],
}

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "agent" / "data" / "version_matrix.json"


def resolve_binary(version: str) -> str:
    attr = "solang_" + version.replace(".", "_")
    out = subprocess.run(
        ["nix", "build", f".#{attr}", "--no-link", "--print-out-paths"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=900,
    )
    if out.returncode != 0:
        raise RuntimeError(f"nix build .#{attr} failed: {out.stderr[-500:]}")
    return out.stdout.strip().splitlines()[-1] + "/bin/solang"


def probe(version: str, binary: str) -> dict:
    # ORACLE_SOLANG_BIN is read at compile time (oracle.compilers._solang_bin)
    old = os.environ.get("ORACLE_SOLANG_BIN")
    os.environ["ORACLE_SOLANG_BIN"] = binary
    try:
        from agent.executor import run_spec_dict

        report = run_spec_dict(dict(SMOKE_SPEC))
    finally:
        if old is None:
            del os.environ["ORACLE_SOLANG_BIN"]
        else:
            os.environ["ORACLE_SOLANG_BIN"] = old
    compile_solang = report.get("compile", {}).get("solang", {})
    compile_ok = bool(compile_solang.get("ok"))
    deploy_polkadot = report.get("deploy", {}).get("polkadot", {}).get("status")
    deploy_evm = report.get("deploy", {}).get("evm", {}).get("status")
    compatible = compile_ok and deploy_polkadot == "success" and deploy_evm == "success"
    note = ""
    if report.get("verdict") == "ERROR":
        note = f"run error: {(report.get('error') or '')[:200]}"
    elif not compile_ok:
        errs = compile_solang.get("errors") or []
        note = f"compile failed: {errs[0][:200] if errs else 'unknown'}"
    elif deploy_polkadot != "success":
        err = report.get("deploy", {}).get("polkadot", {}).get("error") or ""
        note = f"polkadot deploy {deploy_polkadot}: {err[:200]}"
    return {
        "version": version,
        "binary": binary,
        "solang_version_reported": report.get("tool_versions", {}).get("solang"),
        "compile_ok": compile_ok,
        "deploy_evm": deploy_evm,
        "deploy_polkadot": deploy_polkadot,
        "verdict": report.get("verdict"),
        "compatible": compatible,
        "note": note,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bin",
        action="append",
        default=[],
        metavar="VERSION=PATH",
        help="explicit version->binary mapping (default: nix build per version; "
        "0.3.5 defaults to `solang` on PATH)",
    )
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)

    bins: dict[str, str] = {}
    for item in args.bin:
        version, _, path = item.partition("=")
        bins[version] = path

    results = []
    for version in VERSIONS:
        binary = bins.get(version)
        if binary is None:
            binary = "solang" if version == "0.3.5" else resolve_binary(version)
        print(f"[compat] probing solang {version} ({binary}) ...", file=sys.stderr)
        try:
            rec = probe(version, binary)
        except Exception as e:  # noqa: BLE001 - record, never crash on a version
            rec = {
                "version": version,
                "binary": binary,
                "compile_ok": False,
                "deploy_evm": None,
                "deploy_polkadot": None,
                "verdict": "ERROR",
                "compatible": False,
                "note": f"probe crashed: {type(e).__name__}: {e}",
            }
        print(
            f"[compat] {version}: compatible={rec['compatible']} {rec['note']}",
            file=sys.stderr,
        )
        results.append(rec)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=2) + "\n")
    print(f"[compat] wrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
