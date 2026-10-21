"""Storage-mode contrast (T2.5 / RQ1 support): exact-vs-count FP measurement.

Reruns a fixed probe corpus (a findings dir's findings.jsonl + corpus.jsonl,
plus every admitted ground-truth spec) twice: once with
`oracle.storage = "exact"`, once with `"count"`. A STORAGE_MISMATCH that fires
under exact but vanishes under count is a layout/endianness artifact
(spurious); one that persists under count is a real value divergence.

Output eval/rq1/storage_modes.json:

    {"name": ..., "origin": ...,
     "exact": {"storage_mismatch": bool, "earliest_signature": ...},
     "count": {"storage_mismatch": bool, "earliest_signature": ...},
     "spurious_storage_fp": bool}   # fires under exact, vanishes under count

Usage:
    uv run --package solidity-diff-agent python agent/tools/storage_mode_contrast.py \
        --corpus findings/20260923
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agent.executor import divergence_kinds, earliest_signature, run_spec_dict

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "eval" / "rq1" / "storage_modes.json"
GT_DIR = ROOT / "agent" / "data" / "ground_truth"


def run_with_storage(spec: dict, mode: str) -> dict:
    s = dict(spec)
    oracle = dict(s.get("oracle") or {})
    oracle["storage"] = mode
    s["oracle"] = oracle
    report = run_spec_dict(s)
    return {
        "storage_mismatch": "STORAGE_MISMATCH" in divergence_kinds(report),
        "earliest_signature": earliest_signature(report),
        "verdict": report.get("verdict"),
    }


def load_specs(corpus: Path) -> list[tuple[dict, str]]:
    specs: list[tuple[dict, str]] = []
    findings = corpus / "findings.jsonl"
    if findings.exists():
        for line in findings.read_text().strip().splitlines():
            if line.strip():
                specs.append((json.loads(line)["spec"], "finding"))
    corpus_file = corpus / "corpus.jsonl"
    if corpus_file.exists():
        for line in corpus_file.read_text().strip().splitlines():
            if line.strip():
                specs.append((json.loads(line)["spec"], "corpus"))
    if GT_DIR.exists():
        for bug_dir in sorted(GT_DIR.iterdir()):
            spec_path = bug_dir / "spec.json"
            if bug_dir.is_dir() and spec_path.exists():
                specs.append((json.loads(spec_path.read_text()), "ground_truth"))
    return specs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)

    results = []
    for spec, origin in load_specs(args.corpus):
        print(f"[storage-modes] {origin}: {spec.get('name')} ...", file=sys.stderr)
        try:
            exact = run_with_storage(spec, "exact")
            count = run_with_storage(spec, "count")
            results.append(
                {
                    "name": spec.get("name"),
                    "origin": origin,
                    "exact": exact,
                    "count": count,
                    "spurious_storage_fp": exact["storage_mismatch"]
                    and not count["storage_mismatch"],
                }
            )
        except Exception as e:  # noqa: BLE001 - record, never crash mid-corpus
            results.append(
                {
                    "name": spec.get("name"),
                    "origin": origin,
                    "error": f"{type(e).__name__}: {e}",
                }
            )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=2) + "\n")
    spurious = sum(1 for r in results if r.get("spurious_storage_fp"))
    total_exact = sum(1 for r in results if r.get("exact", {}).get("storage_mismatch"))
    print(
        f"[storage-modes] {total_exact} exact-mode STORAGE_MISMATCH, "
        f"{spurious} spurious under count; wrote {args.out}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
