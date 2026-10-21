"""Determinism replay check (T3.5 / RQ5).

Replays every final witness in a findings dir N times and reports verdict +
signature agreement: a deterministic oracle yields the identical verdict and
identical earliest signature on every replay. Output eval/rq5/determinism.json:

    {"id": ..., "name": ..., "replays": int,
     "verdicts": [...], "earliest_signatures": [...],
     "verdict_agreement": bool, "signature_agreement": bool}

Usage:
    uv run --package solidity-diff-agent python agent/tools/replay_check.py \
        --corpus findings/20260923 --replays 5
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agent.executor import earliest_signature, run_spec_dict

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "eval" / "rq5" / "determinism.json"


def replay(spec: dict, n: int) -> dict:
    verdicts = []
    sigs = []
    for _ in range(n):
        report = run_spec_dict(spec)
        verdicts.append(report.get("verdict"))
        sigs.append(earliest_signature(report))
    return {
        "verdicts": verdicts,
        "earliest_signatures": sigs,
        "verdict_agreement": len(set(verdicts)) == 1,
        "signature_agreement": len(set(sigs)) == 1,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--replays", type=int, default=5)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)

    findings = [
        json.loads(line)
        for line in (args.corpus / "findings.jsonl").read_text().strip().splitlines()
        if line.strip()
    ]
    results = []
    for f in findings:
        print(f"[replay-check] {f['id']} ({f.get('name')}) ...", file=sys.stderr)
        entry = {
            "id": f["id"],
            "name": f.get("name"),
            "replays": args.replays,
            **replay(f["spec"], args.replays),
        }
        results.append(entry)
        print(
            f"[replay-check]   verdicts={entry['verdicts']} sigs agree="
            f"{entry['signature_agreement']}",
            file=sys.stderr,
        )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=2) + "\n")
    n_agree = sum(
        1 for r in results if r["verdict_agreement"] and r["signature_agreement"]
    )
    print(
        f"[replay-check] {n_agree}/{len(results)} fully deterministic; wrote {args.out}",
        file=sys.stderr,
    )
    return 0 if n_agree == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
