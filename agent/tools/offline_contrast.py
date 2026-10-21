"""Offline contrast tool (T2.1 / RQ4): on-chain replay vs dry-run-only.

Takes a witness corpus dir (findings.jsonl specs) plus a probe sample
(corpus.jsonl entries) and runs each spec twice — `"execution": "on-chain"`
and `"dry-run-only"` — emitting eval/rq4/contrast.json:

    {"name": ..., "origin": "finding"|"corpus",
     "on_chain":   {"verdict": ..., "earliest_signature": ..., "kinds": [...]},
     "dry_run":    {"verdict": ..., "earliest_signature": ..., "kinds": [...]},
     "committed_calls_before_divergence": int,
     "classification": "replay-required" | "replay-irrelevant" | "no-divergence"
                     | "divergence-drifted" | "dry-run-artifact",
     "state_dependent": bool}

Classification:
  - replay-required:    divergence present on-chain, absent in dry-run-only
  - replay-irrelevant:  divergence present in both, same earliest signature
  - divergence-drifted: both diverge, but the earliest signature differs
                        (dry-run-only sees a different witness — e.g. the
                        pallet-contracts dry-run dispatch error, which the
                        oracle suppresses only when a committed tx corroborates)
  - dry-run-artifact:   absent on-chain, present in dry-run-only (pure FP)
  - no-divergence:      absent in both
`state_dependent` is true when ≥2 committed calls precede (incl.) the earliest
diverging step — the witness class invisible without committed replay.

Usage:
    uv run --package solidity-diff-agent python agent/tools/offline_contrast.py \
        --corpus findings/20260923 --probe-sample 50
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agent.executor import divergence_kinds, earliest_signature, run_spec_dict

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "eval" / "rq4" / "contrast.json"


def committed_calls_before_divergence(spec: dict, report: dict) -> int | None:
    """Committed call steps up to and including the earliest diverging step."""
    ed = report.get("earliest_divergence") or {}
    point = ed.get("point")
    if not isinstance(point, int):
        return None
    calls = 0
    for i, step in enumerate(spec.get("steps", [])):
        if step.get("action", "call") == "call":
            calls += 1
        if i >= point:
            break
    return calls


def run_mode(spec: dict, mode: str) -> dict:
    s = dict(spec)
    s.pop("execution", None)
    s["execution"] = mode
    report = run_spec_dict(s)
    return {
        "verdict": report.get("verdict"),
        "earliest_signature": earliest_signature(report),
        "kinds": sorted(divergence_kinds(report)),
        "_report": report,
    }


def contrast(spec: dict, origin: str) -> dict:
    on_chain = run_mode(spec, "on-chain")
    dry = run_mode(spec, "dry-run-only")
    div_on = on_chain["verdict"] == "DIVERGENCE"
    div_dry = dry["verdict"] == "DIVERGENCE"
    if div_on and not div_dry:
        classification = "replay-required"
    elif div_on and div_dry:
        if on_chain["earliest_signature"] == dry["earliest_signature"]:
            classification = "replay-irrelevant"
        else:
            classification = "divergence-drifted"
    elif div_dry:
        classification = "dry-run-artifact"
    else:
        classification = "no-divergence"
    calls = committed_calls_before_divergence(spec, on_chain["_report"])
    return {
        "name": spec.get("name"),
        "origin": origin,
        "on_chain": {k: v for k, v in on_chain.items() if k != "_report"},
        "dry_run": {k: v for k, v in dry.items() if k != "_report"},
        "committed_calls_before_divergence": calls,
        "classification": classification,
        "state_dependent": calls is not None and calls >= 2,
    }


def load_specs(corpus: Path, probe_sample: int) -> list[tuple[dict, str]]:
    specs: list[tuple[dict, str]] = []
    findings = corpus / "findings.jsonl"
    if findings.exists():
        for line in findings.read_text().strip().splitlines():
            if line.strip():
                specs.append((json.loads(line)["spec"], "finding"))
    corpus_file = corpus / "corpus.jsonl"
    if corpus_file.exists() and probe_sample > 0:
        entries = [
            json.loads(line)
            for line in corpus_file.read_text().strip().splitlines()
            if line.strip()
        ]
        for e in entries[:probe_sample]:
            specs.append((e["spec"], "corpus"))
    return specs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--probe-sample", type=int, default=50)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)

    specs = load_specs(args.corpus, args.probe_sample)
    results = []
    for spec, origin in specs:
        print(f"[contrast] {origin}: {spec.get('name')} ...", file=sys.stderr)
        try:
            results.append(contrast(spec, origin))
        except Exception as e:  # noqa: BLE001 - record, never crash mid-corpus
            results.append(
                {
                    "name": spec.get("name"),
                    "origin": origin,
                    "classification": "error",
                    "error": f"{type(e).__name__}: {e}",
                }
            )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=2) + "\n")
    counts: dict[str, int] = {}
    for r in results:
        counts[r["classification"]] = counts.get(r["classification"], 0) + 1
    print(f"[contrast] {counts}; wrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
