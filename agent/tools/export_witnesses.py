"""Witness dataset export (T4.1).

Exports a findings dir to dataset/witnesses/<id>/:

    spec.orig.json     the pre-reduction spec (finding.original_spec; for
                       legacy pre-L1 findings this equals the stored spec and
                       provenance marks "legacy": true)
    spec.min.json      the stored (reduced) witness spec
    report.min.json    the oracle report of the stored spec
    signature.json     {fingerprint, earliest_signature, signatures}
    provenance.json    compiler/node versions, repo git rev, export timestamp

Plus dataset/SCHEMA.md and dataset/verify_all.py (replays every minimized
spec, asserts the earliest signature matches, exits 1 on any mismatch).

Usage:
    uv run --package solidity-diff-agent python agent/tools/export_witnesses.py \
        --corpus findings/20260923 --out dataset
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from agent.executor import earliest_signature, run_spec_dict

ROOT = Path(__file__).resolve().parents[2]

SCHEMA_MD = """# Witness dataset schema

One directory per witness under `witnesses/<id>/`:

- `spec.orig.json` — spec as discovered (pre-reduction). Legacy findings
  (pre-L1 pipeline) store the reduced spec here too; `provenance.json`
  marks them `"legacy": true`.
- `spec.min.json` — the reduced witness spec (oracle test-environment
  schema; see `oracle/README.md`).
- `report.min.json` — the oracle report produced by replaying
  `spec.min.json` at export time.
- `signature.json` — witness identity: `fingerprint` (sha1 over the sorted
  divergence-signature set), `earliest_signature`, full `signatures` list.
  Signature format: `<kind>|<point>|<function-or-empty>|<relation>`; see
  `oracle/src/oracle/signature.py`.
- `provenance.json` — compiler/node versions at export, repo git revision,
  export timestamp.

Verification: `uv run python dataset/verify_all.py` replays every
`spec.min.json` through the oracle and asserts the earliest signature
matches `signature.json` (exit 1 on any mismatch).
"""

VERIFY_ALL = '''"""Replay every exported witness and assert its signature matches.

Exit 0 iff every witnesses/*/spec.min.json replays to DIVERGENCE with the
earliest signature recorded in signature.json. Run inside the devshell:

    uv run python dataset/verify_all.py
"""

import json
import sys
from pathlib import Path

from agent.executor import earliest_signature, run_spec_dict


def main() -> int:
    root = Path(__file__).parent / "witnesses"
    failures = 0
    for witness in sorted(root.iterdir()):
        if not witness.is_dir():
            continue
        spec = json.loads((witness / "spec.min.json").read_text())
        expected = json.loads((witness / "signature.json").read_text())[
            "earliest_signature"
        ]
        report = run_spec_dict(spec)
        actual = earliest_signature(report)
        ok = report.get("verdict") == "DIVERGENCE" and actual == expected
        print(f"{witness.name}: {'OK' if ok else 'MISMATCH'} ({actual})")
        if not ok:
            failures += 1
    print(f"{failures} mismatch(es)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
'''


def git_rev() -> str:
    out = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT
    )
    return out.stdout.strip() if out.returncode == 0 else "unknown"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=ROOT / "dataset")
    args = parser.parse_args(argv)

    findings = [
        json.loads(line)
        for line in (args.corpus / "findings.jsonl").read_text().strip().splitlines()
        if line.strip()
    ]
    rev = git_rev()
    witnesses_dir = args.out / "witnesses"
    witnesses_dir.mkdir(parents=True, exist_ok=True)
    for f in findings:
        wid = f["id"]
        out_dir = witnesses_dir / wid
        out_dir.mkdir(exist_ok=True)
        report_path = args.corpus / "reports" / f"{wid}.json"
        stored_report = json.loads(report_path.read_text())
        # replay at export time so report.min.json matches the current oracle
        report = run_spec_dict(f["spec"])
        legacy = f.get("original_spec") is None
        orig = f.get("original_spec") or f["spec"]
        (out_dir / "spec.orig.json").write_text(json.dumps(orig, indent=2) + "\n")
        (out_dir / "spec.min.json").write_text(json.dumps(f["spec"], indent=2) + "\n")
        (out_dir / "report.min.json").write_text(json.dumps(report, indent=2) + "\n")
        (out_dir / "signature.json").write_text(
            json.dumps(
                {
                    "fingerprint": wid,
                    "earliest_signature": f.get("earliest_signature")
                    or earliest_signature(report),
                    "signatures": f.get("signatures", []),
                },
                indent=2,
            )
            + "\n"
        )
        (out_dir / "provenance.json").write_text(
            json.dumps(
                {
                    "tool_versions": stored_report.get("tool_versions", {}),
                    "git_rev": rev,
                    "exported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "legacy": legacy,
                    "seed": f.get("seed"),
                    "name": f.get("name"),
                },
                indent=2,
            )
            + "\n"
        )
        print(f"[export] {wid} ({f.get('name')})", file=sys.stderr)
    (args.out / "SCHEMA.md").write_text(SCHEMA_MD)
    (args.out / "verify_all.py").write_text(VERIFY_ALL)
    print(f"[export] {len(findings)} witnesses -> {witnesses_dir}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
