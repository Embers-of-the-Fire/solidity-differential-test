"""One-time fingerprint migration (T0.3): legacy findings -> signature scheme.

Pre-signature findings.jsonl records use the old fingerprint (kinds + detail +
source hash). This tool replays each stored finding's spec through the oracle,
recomputes the signature-based fingerprint, and rewrites the record in place
(findings.jsonl rewrite is the single sanctioned exception to append-only;
one line is logged to stderr per record). The finding id changes to the new
fingerprint and the stored report is rewritten under reports/<new-id>.json
(old report file removed).

Records whose replay no longer yields DIVERGENCE are left untouched and
reported on stderr — a verdict flip is a datum, not something to paper over.

Usage (from the repo root):
    uv run --package solidity-diff-agent python agent/tools/refingerprint.py \
        findings/20260923
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agent.executor import earliest_signature, run_spec_dict
from agent.store import fingerprint


def migrate(findings_dir: Path) -> int:
    findings_path = findings_dir / "findings.jsonl"
    if not findings_path.exists():
        print(f"no findings.jsonl in {findings_dir}", file=sys.stderr)
        return 1
    records = [
        json.loads(line)
        for line in findings_path.read_text().strip().splitlines()
        if line.strip()
    ]
    out_records = []
    exit_code = 0
    for rec in records:
        old_id = rec["id"]
        report = run_spec_dict(rec["spec"])
        if report.get("verdict") != "DIVERGENCE":
            print(
                f"[refingerprint] {old_id} ({rec.get('name')}): replay verdict "
                f"{report.get('verdict')} != DIVERGENCE — record left untouched",
                file=sys.stderr,
            )
            out_records.append(rec)
            exit_code = 1
            continue
        sigs = {
            d["signature"] for d in report.get("divergences", []) if d.get("signature")
        }
        new_id = fingerprint(sigs)
        rec["fingerprint"] = new_id
        rec["id"] = new_id
        rec["signatures"] = sorted(sigs)
        rec["earliest_signature"] = earliest_signature(report)
        out_records.append(rec)
        reports_dir = findings_dir / "reports"
        reports_dir.mkdir(exist_ok=True)
        (reports_dir / f"{new_id}.json").write_text(json.dumps(report, indent=2))
        old_report = reports_dir / f"{old_id}.json"
        if old_report.exists() and old_id != new_id:
            old_report.unlink()
        print(
            f"[refingerprint] {old_id} -> {new_id} ({rec.get('name')}): "
            f"earliest={rec['earliest_signature']}",
            file=sys.stderr,
        )
    findings_path.write_text("".join(json.dumps(r) + "\n" for r in out_records))
    return exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("findings_dir", type=Path)
    args = parser.parse_args(argv)
    return migrate(args.findings_dir)


if __name__ == "__main__":
    sys.exit(main())
