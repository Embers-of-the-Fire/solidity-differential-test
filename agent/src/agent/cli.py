"""Command-line interface for the AI-in-the-loop bug hunter."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import AgentConfigError, load_config
from .evaluate import EvalConfigError, load_eval_config, run_matrix
from .executor import Executor, divergence_kinds
from .hypotheses import load_notebook
from .loop import HuntLoop
from .seeds import load_seeds
from .store import FindingStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="solidity-diff-agent",
        description="AI-in-the-loop differential bug hunter: solc (EVM) vs solang (Polkadot WASM)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    hunt = sub.add_parser("hunt", help="run the generate-run-triage-minimize loop")
    hunt.add_argument("--rounds", type=int, metavar="N", help="max hunt rounds")
    hunt.add_argument("--llm-calls", type=int, metavar="N", help="LLM call budget")
    hunt.add_argument("--oracle-runs", type=int, metavar="N", help="oracle run budget")
    hunt.add_argument(
        "--saturation-window",
        type=int,
        metavar="K",
        help="stop after K rounds with no new findings, kinds or hypothesis changes",
    )
    hunt.add_argument("--parallel", type=int, metavar="K", help="parallel oracle runs")
    hunt.add_argument(
        "--p-mutate",
        type=float,
        metavar="P",
        help="probability of mutating a corpus parent instead of generating "
        "from scratch (0.0 = generation-only baseline)",
    )
    hunt.add_argument(
        "--findings-dir", metavar="DIR", default=None, help="findings DB directory"
    )
    hunt.add_argument(
        "--seeds", metavar="IDS", help="comma-separated seed ids to restrict to"
    )
    hunt.add_argument(
        "--seeds-dir",
        metavar="DIR",
        default=None,
        help="load seed cards from DIR instead of the packaged seeds/",
    )
    hunt.add_argument("--rng-seed", type=int, metavar="INT", help="sampling seed")
    hunt.add_argument("--quiet", action="store_true")

    report = sub.add_parser("report", help="print deduplicated findings")
    report.add_argument("--findings-dir", metavar="DIR", default=None)

    hypo = sub.add_parser("hypotheses", help="print per-seed hypothesis notebooks")
    hypo.add_argument("--findings-dir", metavar="DIR", default=None)
    hypo.add_argument(
        "--seeds-dir",
        metavar="DIR",
        default=None,
        help="load seed cards from DIR instead of the packaged seeds/",
    )

    cost = sub.add_parser(
        "cost", help="print aggregated token/cost/time usage statistics"
    )
    cost.add_argument("--findings-dir", metavar="DIR", default=None)

    replay = sub.add_parser("replay", help="re-run a finding's reproducer")
    replay.add_argument("finding_id", help="finding id from `report`")
    replay.add_argument("--findings-dir", metavar="DIR", default=None)

    ev = sub.add_parser(
        "eval", help="run an ablation matrix (configs x repeats x budgets)"
    )
    ev.add_argument(
        "--config", required=True, metavar="JSON", help="ablation matrix file"
    )
    ev.add_argument(
        "--out-root",
        metavar="DIR",
        default=None,
        help="runs root (default: <findings-dir>/eval)",
    )
    ev.add_argument("--findings-dir", metavar="DIR", default=None)
    ev.add_argument("--quiet", action="store_true")
    return parser


def _cmd_hunt(args: argparse.Namespace) -> int:
    if args.p_mutate is not None and not 0.0 <= args.p_mutate <= 1.0:
        print("--p-mutate must be in [0.0, 1.0]", file=sys.stderr)
        return 2
    cfg = load_config(
        findings_dir=args.findings_dir,
        llm_calls=args.llm_calls,
        oracle_runs=args.oracle_runs,
        saturation_window=args.saturation_window,
        parallel=args.parallel,
        p_mutate=args.p_mutate,
        seeds_dir=args.seeds_dir,
    )
    only = args.seeds.split(",") if args.seeds else None
    loop = HuntLoop(
        cfg,
        rng_seed=args.rng_seed,
        log=(lambda *_: None) if args.quiet else print,
    )
    try:
        summary = loop.hunt(policy=loop.default_policy(args.rounds), only_seeds=only)
    finally:
        loop.executor.close()
    print(
        f"\nhunt done: {summary['rounds']} rounds, {summary['new_findings']} new finding(s) "
        f"({summary['stop_reason']})"
    )
    hyp = summary["hypotheses"]
    print(
        f"hypotheses: {hyp['open']} open, {hyp['confirmed']} confirmed, {hyp['refuted']} refuted"
    )
    totals = summary["usage"]["totals"]
    print(
        f"llm: {totals['calls']} calls, {totals['total_tokens']} tokens "
        f"({totals['cached_prompt_tokens']} cached), ${totals['cost_usd']:.6f}, "
        f"{totals['latency_ms'] / 1000:.1f}s in LLM; wall {summary['elapsed_ms'] / 1000:.1f}s"
    )
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    store = FindingStore(args.findings_dir or "findings")
    findings = store.findings()
    if not findings:
        print("no findings yet")
        return 0
    print(f"{len(findings)} finding(s):\n")
    for f in findings:
        triage = f.get("triage", {})
        print(f"  {f['id']}  [{f.get('seed')}] {','.join(f.get('kinds', []))}")
        print(f"    {triage.get('summary', '(no summary)')}")
        print(f"    confidence={triage.get('confidence')} blame={triage.get('blame')}")
        print(
            f"    spec: {f.get('spec', {}).get('name')}  report: reports/{f['id']}.json"
        )
    return 0


def _cmd_hypotheses(args: argparse.Namespace) -> int:
    root = args.findings_dir or "findings"
    any_found = False
    for seed in load_seeds(args.seeds_dir):
        nb = load_notebook(root, seed.id)
        if not nb["hypotheses"]:
            continue
        any_found = True
        print(f"{seed.id}: {seed.title}")
        for h in nb["hypotheses"]:
            print(f"  [{h['status']}] {h['id']}: {h['statement']}")
            if h["status"] == "open":
                print(f"    next probe: {h['next_probe']}")
        print()
    if not any_found:
        print("no hypotheses recorded yet")
    return 0


def _cmd_cost(args: argparse.Namespace) -> int:
    store = FindingStore(args.findings_dir or "findings")
    summary = store.usage_summary()
    totals = summary["totals"]
    if totals["calls"] == 0:
        print("no LLM usage recorded yet")
        return 0
    print("LLM usage totals:")
    print(f"  calls:    {totals['calls']} ({totals['errors']} errors)")
    print(
        f"  tokens:   {totals['total_tokens']} total "
        f"({totals['prompt_tokens']} prompt, {totals['cached_prompt_tokens']} cached, "
        f"{totals['completion_tokens']} completion)"
    )
    print(f"  cost:     ${totals['cost_usd']:.6f}")
    print(
        f"  latency:  {totals['latency_ms'] / 1000:.1f}s total, "
        f"{totals['avg_latency_ms']:.0f}ms avg/call"
    )
    if summary["per_stage"]:
        print("\nper stage:")
        print(f"  {'stage':<10} {'calls':>6} {'tokens':>10} {'cost':>12} {'avg ms':>8}")
        for stage, s in summary["per_stage"].items():
            print(
                f"  {stage:<10} {s['calls']:>6} {s['total_tokens']:>10} "
                f"${s['cost_usd']:>11.6f} {s['avg_latency_ms']:>8.0f}"
            )
    per_seed: dict[str, dict[str, float]] = {}
    for probe in store.probes():
        seed = probe.get("seed") or "?"
        acc = per_seed.setdefault(
            seed, {"probes": 0, "tokens": 0, "cost_usd": 0.0, "round_ms": 0.0}
        )
        acc["probes"] += 1
        usage = probe.get("usage") or {}
        timing = probe.get("timing") or {}
        acc["tokens"] += usage.get("total_tokens") or 0
        acc["cost_usd"] += usage.get("cost_usd") or 0.0
        acc["round_ms"] += timing.get("round_ms") or 0.0
    if per_seed:
        print("\nper seed (probe-level):")
        print(
            f"  {'seed':<28} {'probes':>6} {'tokens':>10} {'cost':>12} {'round s':>9}"
        )
        for seed, s in sorted(per_seed.items()):
            print(
                f"  {seed:<28} {int(s['probes']):>6} {int(s['tokens']):>10} "
                f"${s['cost_usd']:>11.6f} {s['round_ms'] / 1000:>9.1f}"
            )
    return 0


def _cmd_replay(args: argparse.Namespace) -> int:
    store = FindingStore(args.findings_dir or "findings")
    finding = store.get_finding(args.finding_id)
    if finding is None:
        print(f"finding {args.finding_id!r} not found", file=sys.stderr)
        return 2
    report = Executor(parallel=1).run(finding["spec"])
    kinds = divergence_kinds(report)
    print(f"replay verdict: {report.get('verdict')} kinds={sorted(kinds) or '-'}")
    return 0 if report.get("verdict") == "PASS" else 1


def _cmd_eval(args: argparse.Namespace) -> int:
    try:
        matrix = load_eval_config(args.config)
    except EvalConfigError as e:
        print(f"eval config error: {e}", file=sys.stderr)
        return 2
    cfg = load_config(findings_dir=args.findings_dir)
    cfg.check_llm()  # fail fast before starting a long matrix
    out_root = Path(args.out_root) if args.out_root else cfg.findings_dir / "eval"
    log = (lambda *_: None) if args.quiet else print
    summary = run_matrix(matrix, base_config=cfg, out_root=out_root, log=log)
    print(
        f"\neval done: {summary['n_runs']} run(s); summary: {out_root / 'summary.json'}"
    )
    for name, agg in summary["configs"].items():
        f = agg["unique_findings"]
        print(
            f"  {name}: findings median {f['median']} "
            f"(min {f['min']}, max {f['max']}); "
            f"{agg['n_ok']} ok / {agg['n_failed']} failed; "
            f"stop reasons: {agg['stop_reasons']}"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "hunt":
            return _cmd_hunt(args)
        if args.command == "report":
            return _cmd_report(args)
        if args.command == "hypotheses":
            return _cmd_hypotheses(args)
        if args.command == "cost":
            return _cmd_cost(args)
        if args.command == "replay":
            return _cmd_replay(args)
        if args.command == "eval":
            return _cmd_eval(args)
    except AgentConfigError as e:
        print(f"configuration error: {e}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
