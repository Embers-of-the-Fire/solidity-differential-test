"""Reduction evaluation + predicate-drift experiment (T3.3 / RQ3).

For every witness in a findings dir, runs the L1 reduction pipeline under
both acceptance predicates — "signature" (default) and "kind" (the lenient
pre-T0.2 predicate) — with no LLM stage (reduce_llm_rounds=0; the LLM tier is
ablated separately). Emits eval/rq3/reduction.json:

    {"id": ..., "name": ...,
     "before": {"chars": int, "steps": int},
     "arms": {"signature": {"after": {...}, "oracle_runs": int,
                            "stages": {...}, "verified_one_minimal": bool,
                            "final_earliest_signature": str, "drift": false},
              "kind":      {... "drift": bool}}}
`drift` is true when the kind arm's final earliest-signature differs from the
original witness's — predicate drift, audited manually (drift-audit.md).

Usage:
    uv run --package solidity-diff-agent python agent/tools/reduce_eval.py \
        --corpus findings/20260923
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agent.executor import (
    divergence_signatures,
    earliest_signature,
    run_spec_dict,
)
from agent.minimize import ReduceConfig, minimize
from agent.store import fingerprint

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "eval" / "rq3" / "reduction.json"


def measure(spec: dict) -> dict:
    return {
        "chars": len(spec.get("solidity", "")),
        "steps": len(spec.get("steps", [])),
    }


def reduce_arm(spec: dict, report: dict, predicate: str) -> dict:
    config = ReduceConfig(predicate=predicate, llm_rounds=0)
    min_spec, minimality = minimize(spec, report, run_spec_dict, config=config)
    final_report = run_spec_dict(min_spec)
    orig_sig = earliest_signature(report)
    final_sig = earliest_signature(final_report)
    return {
        "after": measure(min_spec),
        "oracle_runs": minimality["oracle_runs"],
        "stages": minimality["stages"],
        "verified_one_minimal": minimality["verified_one_minimal"],
        "residual_deletable": minimality["residual_deletable"],
        "final_verdict": final_report.get("verdict"),
        "final_earliest_signature": final_sig,
        "final_fingerprint": fingerprint(divergence_signatures(final_report)),
        "drift": final_sig != orig_sig,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)

    findings = [
        json.loads(line)
        for line in (args.corpus / "findings.jsonl").read_text().strip().splitlines()
        if line.strip()
    ]
    results = []
    for f in findings:
        report_path = args.corpus / "reports" / f"{f['id']}.json"
        report = json.loads(report_path.read_text())
        print(f"[reduce-eval] {f['id']} ({f.get('name')}) ...", file=sys.stderr)
        entry = {
            "id": f["id"],
            "name": f.get("name"),
            "earliest_signature": f.get("earliest_signature"),
            "before": measure(f["spec"]),
            "arms": {},
        }
        for predicate in ("signature", "kind"):
            try:
                entry["arms"][predicate] = reduce_arm(f["spec"], report, predicate)
            except Exception as e:  # noqa: BLE001 - record, never crash mid-corpus
                entry["arms"][predicate] = {"error": f"{type(e).__name__}: {e}"}
            print(
                f"[reduce-eval]   {predicate}: {entry['arms'][predicate]}",
                file=sys.stderr,
            )
        results.append(entry)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=2) + "\n")
    drift = sum(1 for r in results if r["arms"].get("kind", {}).get("drift"))
    print(
        f"[reduce-eval] {len(results)} witnesses, {drift} drifted under the "
        f"kind predicate; wrote {args.out}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
