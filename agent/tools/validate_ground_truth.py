"""Ground-truth validation (T2.3 / RQ1a).

Every spec under agent/data/ground_truth/<bug-id>/spec.json encodes a known
historical solang bug and carries annotations (ignored by the spec loader):

    "_affected": ["0.3.1", ...],   # solang versions that must DIVERGE
    "_fixed_in": "0.3.4",          # first fixed version: must PASS
    "_source": "https://github.com/.../issues/NNN"   # upstream reference

The contract: DIVERGENCE on every affected version, PASS on the fixed
version (oracle run with ORACLE_SOLANG_BIN pinned per version). Specs that
violate the contract are moved to ground_truth/rejected/ with a one-line
reason file — an honest rejection is a datum, not a failure.

Results are written to eval/rq1/oracle_validation.json.

Usage (from the repo root):
    uv run --package solidity-diff-agent python agent/tools/validate_ground_truth.py
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GT_DIR = ROOT / "agent" / "data" / "ground_truth"
OUT = ROOT / "eval" / "rq1" / "oracle_validation.json"

_binary_cache: dict[str, str] = {}


def solang_bin(version: str) -> str:
    if version not in _binary_cache:
        if version == "0.3.5":
            _binary_cache[version] = "solang"
        else:
            attr = "solang_" + version.replace(".", "_")
            out = subprocess.run(
                ["nix", "build", f".#{attr}", "--no-link", "--print-out-paths"],
                capture_output=True,
                text=True,
                cwd=ROOT,
                timeout=900,
            )
            if out.returncode != 0:
                raise RuntimeError(f"nix build .#{attr} failed: {out.stderr[-300:]}")
            _binary_cache[version] = out.stdout.strip().splitlines()[-1] + "/bin/solang"
    return _binary_cache[version]


def run_with_version(spec: dict, version: str) -> dict:
    old = os.environ.get("ORACLE_SOLANG_BIN")
    os.environ["ORACLE_SOLANG_BIN"] = solang_bin(version)
    try:
        from agent.executor import run_spec_dict

        return run_spec_dict(spec)
    finally:
        if old is None:
            del os.environ["ORACLE_SOLANG_BIN"]
        else:
            os.environ["ORACLE_SOLANG_BIN"] = old


def validate_one(bug_dir: Path) -> dict:
    spec = json.loads((bug_dir / "spec.json").read_text())
    affected = spec.get("_affected", [])
    fixed_in = spec.get("_fixed_in")
    result = {
        "bug_id": bug_dir.name,
        "affected": affected,
        "fixed_in": fixed_in,
        "source": spec.get("_source"),
        "runs": [],
        "admitted": True,
        "reason": "",
    }

    def check(version: str, expect: str) -> bool:
        report = run_with_version(spec, version)
        verdict = report.get("verdict")
        sig = (report.get("earliest_divergence") or {}).get("signature")
        ok = verdict == expect
        result["runs"].append(
            {
                "version": version,
                "expect": expect,
                "verdict": verdict,
                "earliest_signature": sig,
                "ok": ok,
            }
        )
        return ok

    try:
        for version in affected:
            if not check(version, "DIVERGENCE"):
                result["admitted"] = False
                result["reason"] = f"expected DIVERGENCE on affected {version}"
                break
        if result["admitted"] and fixed_in and not check(fixed_in, "PASS"):
            result["admitted"] = False
            result["reason"] = f"expected PASS on fixed {fixed_in}"
    except Exception as e:  # noqa: BLE001 - rejection is a datum, not a crash
        result["admitted"] = False
        result["reason"] = f"validation crashed: {type(e).__name__}: {e}"
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", type=Path, default=GT_DIR)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument(
        "--no-reject-move",
        action="store_true",
        help="report rejections without moving specs to rejected/",
    )
    args = parser.parse_args(argv)

    results = []
    for bug_dir in sorted(args.dir.iterdir()):
        if not (bug_dir.is_dir() and (bug_dir / "spec.json").exists()):
            continue
        print(f"[ground-truth] validating {bug_dir.name} ...", file=sys.stderr)
        res = validate_one(bug_dir)
        status = "ADMITTED" if res["admitted"] else f"REJECTED ({res['reason']})"
        print(f"[ground-truth] {bug_dir.name}: {status}", file=sys.stderr)
        results.append(res)
        if not res["admitted"] and not args.no_reject_move:
            rejected = args.dir / "rejected"
            rejected.mkdir(exist_ok=True)
            target = rejected / bug_dir.name
            if target.exists():
                import shutil

                shutil.rmtree(target)
            bug_dir.rename(target)
            (target / "REASON.txt").write_text(res["reason"] + "\n")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=2) + "\n")
    admitted = sum(1 for r in results if r["admitted"])
    print(
        f"[ground-truth] {admitted}/{len(results)} admitted; wrote {args.out}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
