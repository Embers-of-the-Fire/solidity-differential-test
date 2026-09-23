"""Hunt loop orchestration: generate -> run -> triage -> minimize -> dedup."""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from typing import Any

from .config import AgentConfig
from .executor import Executor, OracleRunner, divergence_kinds
from .generator import generate_spec
from .hypotheses import load_notebook, summary_counts
from .llm import ChatClient, LLMClient, LLMError
from .minimize import minimize
from .reflect import reflect_notebook
from .seeds import load_seeds, pick_seed
from .stop import LoopState, StopPolicy
from .store import FindingStore
from .triage import triage_report


class HuntLoop:
    def __init__(
        self,
        cfg: AgentConfig,
        *,
        client: ChatClient | None = None,
        executor: OracleRunner | None = None,
        store: FindingStore | None = None,
        rng_seed: int | None = None,
        log: Callable[[str], None] = print,
    ):
        self.cfg = cfg
        self.client = client or LLMClient(cfg)
        self.executor = executor or Executor(cfg.parallel)
        self.store = store or FindingStore(cfg.findings_dir)
        self.rng = random.Random(rng_seed)
        self.log = log

    def _is_resolved(self, seed_id: str) -> bool:
        """A seed is resolved when it has hypotheses and none are open."""
        nb = load_notebook(self.store.root, seed_id)
        return bool(nb["hypotheses"]) and all(
            h["status"] != "open" for h in nb["hypotheses"]
        )

    def round(self, only_seeds: list[str] | None = None) -> dict[str, Any]:
        """One generate-run-triage-reflect cycle. Returns a probe summary."""
        t_round = time.perf_counter()
        phase_ms: dict[str, float] = {}
        usage_mark = self.client.usage_marker()
        seeds = load_seeds()
        resolved = {s.id for s in seeds if self._is_resolved(s.id)}
        seed = pick_seed(
            seeds, self.store.seed_stats(), self.rng, only=only_seeds, resolved=resolved
        )
        self.log(f"[seed] {seed.id}: {seed.title}")

        notebook = load_notebook(self.store.root, seed.id)
        t0 = time.perf_counter()
        try:
            spec = generate_spec(
                self.client, seed, self.store.recent_probes(), notebook
            )
        except LLMError as e:
            phase_ms["generate_ms"] = (time.perf_counter() - t0) * 1000.0
            self.log(f"[generate] failed: {e}")
            return {
                "seed": seed.id,
                "category": "generation_failed",
                "error": str(e),
                "timing": phase_ms,
                "usage": self.client.usage_since(usage_mark)["totals"],
            }
        phase_ms["generate_ms"] = (time.perf_counter() - t0) * 1000.0

        self.log(f"[run] {spec.get('name')} ({len(spec.get('steps', []))} steps)")
        t0 = time.perf_counter()
        report = self.executor.run(spec)
        phase_ms["oracle_ms"] = (time.perf_counter() - t0) * 1000.0
        verdict = report.get("verdict")
        kinds = divergence_kinds(report)
        self.log(f"[run] verdict={verdict} kinds={sorted(kinds) or '-'}")

        t0 = time.perf_counter()
        triage = triage_report(self.client, spec, report)
        phase_ms["triage_ms"] = (time.perf_counter() - t0) * 1000.0
        category = triage["category"]
        self.log(
            f"[triage] {category}: {triage.get('summary', triage.get('rationale'))}"
        )

        phase_ms["round_ms"] = (time.perf_counter() - t_round) * 1000.0
        usage = self.client.usage_since(usage_mark)["totals"]
        self.store.record_probe(
            spec=spec,
            report=report,
            seed_id=seed.id,
            category=category,
            timing=phase_ms,
            usage=usage,
            oracle_runs_total=self.executor.runs,
            llm_calls_total=self.client.calls,
        )
        self.store.note_seed_result(seed.id, kinds)

        if category != "error":
            t0 = time.perf_counter()
            notebook = reflect_notebook(
                self.client, self.store.root, seed, spec, report, triage, log=self.log
            )
            phase_ms["reflect_ms"] = (time.perf_counter() - t0) * 1000.0

        summary: dict[str, Any] = {
            "seed": seed.id,
            "name": spec.get("name"),
            "verdict": verdict,
            "category": category,
            "kinds": sorted(kinds),
            "hypotheses_open": sum(
                1 for h in notebook["hypotheses"] if h["status"] == "open"
            ),
            "timing": phase_ms,
            "usage": usage,
        }

        if category == "bug_candidate":
            self.log("[minimize] shrinking reproducer ...")
            t0 = time.perf_counter()
            small_spec = minimize(spec, report, self.executor.run, self.client)
            small_report = self.executor.run(small_spec)
            phase_ms["minimize_ms"] = (time.perf_counter() - t0) * 1000.0
            summary["usage"] = self.client.usage_since(usage_mark)["totals"]
            summary["timing"] = phase_ms
            if divergence_kinds(small_report) >= kinds:
                finding_id = self.store.add_finding(
                    spec=small_spec,
                    report=small_report,
                    triage=triage,
                    seed_id=seed.id,
                    timing=phase_ms,
                    usage=summary["usage"],
                )
                if finding_id:
                    self.log(f"[finding] NEW {finding_id}: {triage.get('summary')}")
                    summary["finding_id"] = finding_id
                else:
                    self.log("[finding] duplicate of an existing finding")
                    summary["finding_id"] = None
            else:
                self.log(
                    "[minimize] divergence lost during minimization; kept original"
                )
                finding_id = self.store.add_finding(
                    spec=spec,
                    report=report,
                    triage=triage,
                    seed_id=seed.id,
                    timing=phase_ms,
                    usage=summary["usage"],
                )
                summary["finding_id"] = finding_id
        phase_ms["round_ms"] = (time.perf_counter() - t_round) * 1000.0
        return summary

    def default_policy(self, max_rounds: int | None = None) -> StopPolicy:
        """Policy from config defaults; callers may build their own instead."""
        return StopPolicy(
            max_rounds=max_rounds,
            oracle_runs_budget=self.cfg.oracle_runs_budget,
            llm_calls_budget=self.cfg.llm_calls_budget,
            saturation_window=self.cfg.saturation_window,
        )

    def hunt(
        self, policy: StopPolicy | None = None, only_seeds: list[str] | None = None
    ) -> dict[str, Any]:
        """Run rounds until the stop policy fires. Returns a hunt summary."""
        if policy is None:
            policy = self.default_policy()
        t_hunt = time.perf_counter()
        state = LoopState()
        findings_before = len(self.store.findings())
        seen_kinds: set[str] = set()
        seeds = load_seeds()
        prev_counts = summary_counts(
            [load_notebook(self.store.root, s.id) for s in seeds]
        )
        stop = None
        while True:
            state.oracle_runs = self.executor.runs
            state.llm_calls = self.client.calls
            if (reason := policy.check(state)) is not None:
                stop = reason
                break
            summary = self.round(only_seeds=only_seeds)
            state.rounds += 1
            totals = self.client.usage_totals()["totals"]
            self.log(
                f"[budget] llm_calls={self.client.calls}/{policy.llm_calls_budget} "
                f"oracle_runs={self.executor.runs}/{policy.oracle_runs_budget} "
                f"tokens={totals['total_tokens']} cost=${totals['cost_usd']:.6f}"
            )
            kinds = set(summary.get("kinds") or [])
            notebooks = [load_notebook(self.store.root, s.id) for s in seeds]
            counts = summary_counts(notebooks)
            signal = bool(
                summary.get("finding_id") or kinds - seen_kinds or counts != prev_counts
            )
            seen_kinds |= kinds
            prev_counts = counts
            state.signal_history.append(signal)
        notebooks = [load_notebook(self.store.root, s.id) for s in seeds]
        return {
            "rounds": state.rounds,
            "stop_reason": stop,
            "new_findings": len(self.store.findings()) - findings_before,
            "llm_calls": self.client.calls,
            "oracle_runs": self.executor.runs,
            "elapsed_ms": (time.perf_counter() - t_hunt) * 1000.0,
            "usage": self.client.usage_totals(),
            "hypotheses": summary_counts(notebooks),
        }
