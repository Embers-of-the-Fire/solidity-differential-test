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
from .mutate import llm_mutants, programmatic_mutants
from .reflect import reflect_notebook
from .seeds import load_seeds, pick_seed
from .stop import LoopState, StopPolicy
from .store import FindingStore, fingerprint
from .triage import triage_report

# Ranking used to pick a batch round's headline outcome.
_CATEGORY_RANK = {
    "error": 0,
    "invalid_probe": 0,
    "pass": 1,
    "oracle_artifact": 2,
    "known_semantic": 3,
    "bug_candidate": 4,
}


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

        # Two-level scheduling: topic level (pick_seed above) -> input level
        # (corpus parent selection). A selected parent produces a whole batch
        # of mutants; no parent (or p_mutate=0) is the generation-only path.
        parent = None
        if self.cfg.p_mutate > 0 and self.rng.random() < self.cfg.p_mutate:
            parent = self.store.corpus.select_parent(seed.id, self.rng)

        if parent is not None:
            return self._mutation_round(seed, notebook, parent, usage_mark, t_round)

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
        parent_id = None
        origin = "generated"
        spec["meta"] = {"parent_id": parent_id, "origin": origin}

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
            parent_id=parent_id,
            origin=origin,
        )
        self.store.note_seed_result(seed.id, kinds)

        corpus = self.store.corpus
        detail = "; ".join(d.get("detail", "") for d in report.get("divergences", []))
        fp = fingerprint(kinds, detail, spec.get("solidity", ""))
        entry = corpus.admit(
            spec=spec,
            report=report,
            seed_id=seed.id,
            parent_id=parent_id,
            origin=origin,
            category=category,
            known_finding=fp in self.store.known_fingerprints(),
        )
        if entry is not None:
            self.log(f"[corpus] admitted {entry['id']} ({entry['admitted_by']})")
        corpus.decay()
        corpus.save()

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
            "parent_id": parent_id,
            "origin": origin,
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

    def _mutation_round(
        self,
        seed,
        notebook: dict[str, Any],
        parent: dict[str, Any],
        usage_mark: int,
        t_round: float,
    ) -> dict[str, Any]:
        """One mutation round: batch of mutants from a corpus parent.

        Batch shape: free programmatic mutants + one LLM batch-mutation call,
        executed together via `Executor.run_many`. LLM reflect runs per
        divergent mutant, minimize per bug_candidate (fingerprint dedup
        first); discarded invalid LLM mutants are recorded as full probes.
        """
        phase_ms: dict[str, float] = {}
        parent_id = parent["id"]
        parent_spec = parent["spec"]
        corpus = self.store.corpus

        t0 = time.perf_counter()
        prog, prog_failures = programmatic_mutants(
            parent_spec,
            self.rng,
            k=self.cfg.prog_mutants_per_round,
            ops_per_mutant=self.cfg.prog_ops_per_mutant,
        )
        if prog_failures:
            self.log(f"[mutate] {prog_failures} programmatic operator failure(s)")
        for i, m in enumerate(prog):
            m["name"] = f"{parent_spec.get('name', 'mutant')}-p{i}"
        outcome = parent["outcome"]
        outcome_str = (
            f"{outcome.get('verdict')}/{outcome.get('category')} "
            f"kinds={','.join(outcome.get('kinds') or []) or '-'}"
        )
        valid: list[dict[str, Any]] = []
        invalid: list[dict[str, Any]] = []
        if self.cfg.llm_mutants_per_round > 0:
            try:
                valid, invalid = llm_mutants(
                    self.client,
                    parent_spec,
                    outcome_str,
                    seed,
                    notebook,
                    self.cfg.llm_mutants_per_round,
                )
            except LLMError as e:
                self.log(f"[mutate] LLM batch failed: {e}")
        phase_ms["mutate_ms"] = (time.perf_counter() - t0) * 1000.0

        batch = [(m, "mutated_prog") for m in prog] + [
            (m, "mutated_llm") for m in valid
        ]
        self.log(
            f"[mutate] parent {parent_id}: {len(prog)} programmatic + "
            f"{len(valid)} LLM mutants ({len(invalid)} discarded)"
        )
        if not batch:
            self.log("[mutate] empty batch; falling back to generation")
            t0 = time.perf_counter()
            try:
                spec = generate_spec(
                    self.client, seed, self.store.recent_probes(), notebook
                )
            except LLMError as e:
                phase_ms["generate_ms"] = (time.perf_counter() - t0) * 1000.0
                return {
                    "seed": seed.id,
                    "category": "generation_failed",
                    "error": str(e),
                    "timing": phase_ms,
                    "usage": self.client.usage_since(usage_mark)["totals"],
                }
            spec["meta"] = {"parent_id": None, "origin": "generated"}
            batch = [(spec, "generated")]

        for spec, origin in batch:
            spec["meta"] = {"parent_id": parent_id, "origin": origin}

        # Discarded invalid LLM mutants: full probe records (no oracle run),
        # and the parent's energy is penalized per the corpus rules.
        for cand in invalid:
            cand["meta"] = {"parent_id": parent_id, "origin": "mutated_llm"}
            self.store.record_probe(
                spec=cand,
                report={"verdict": "INVALID", "divergences": []},
                seed_id=seed.id,
                category="invalid_probe",
                parent_id=parent_id,
                origin="mutated_llm",
                oracle_runs_total=self.executor.runs,
                llm_calls_total=self.client.calls,
            )
            corpus.record_offspring(parent_id, "invalid")

        t0 = time.perf_counter()
        reports = self.executor.run_many([s for s, _ in batch])
        phase_ms["oracle_ms"] = (time.perf_counter() - t0) * 1000.0

        t0 = time.perf_counter()
        triages = [
            triage_report(self.client, spec, report)
            for (spec, _), report in zip(batch, reports, strict=True)
        ]
        phase_ms["triage_ms"] = (time.perf_counter() - t0) * 1000.0

        known_fps = self.store.known_fingerprints()
        per_mutant: list[dict[str, Any]] = []
        union_kinds: set[str] = set()
        for (spec, origin), report, triage in zip(batch, reports, triages, strict=True):
            verdict = report.get("verdict")
            kinds = divergence_kinds(report)
            union_kinds |= kinds
            category = triage["category"]
            self.log(
                f"[run] {spec.get('name')} verdict={verdict} "
                f"kinds={sorted(kinds) or '-'} category={category}"
            )
            self.store.record_probe(
                spec=spec,
                report=report,
                seed_id=seed.id,
                category=category,
                parent_id=parent_id,
                origin=origin,
                oracle_runs_total=self.executor.runs,
                llm_calls_total=self.client.calls,
            )
            self.store.note_seed_result(seed.id, kinds)
            corpus.record_offspring(
                parent_id,
                corpus.classify_offspring(
                    parent=parent, spec=spec, report=report, category=category
                ),
            )
            detail = "; ".join(
                d.get("detail", "") for d in report.get("divergences", [])
            )
            fp = fingerprint(kinds, detail, spec.get("solidity", ""))
            entry = corpus.admit(
                spec=spec,
                report=report,
                seed_id=seed.id,
                parent_id=parent_id,
                origin=origin,
                category=category,
                known_finding=fp in known_fps,
            )
            if entry is not None:
                self.log(f"[corpus] admitted {entry['id']} ({entry['admitted_by']})")
            per_mutant.append(
                {
                    "name": spec.get("name"),
                    "origin": origin,
                    "verdict": verdict,
                    "category": category,
                    "kinds": sorted(kinds),
                }
            )
        corpus.decay()
        corpus.save()

        # LLM follow-up per divergent mutant: reflect on each divergence,
        # minimize each bug_candidate (known fingerprints skipped first).
        t0 = time.perf_counter()
        for (spec, _), report, triage in zip(batch, reports, triages, strict=True):
            if report.get("verdict") == "DIVERGENCE":
                notebook = reflect_notebook(
                    self.client,
                    self.store.root,
                    seed,
                    spec,
                    report,
                    triage,
                    log=self.log,
                )
        phase_ms["reflect_ms"] = (time.perf_counter() - t0) * 1000.0

        finding_ids: list[str] = []
        t0 = time.perf_counter()
        for (spec, _), report, triage in zip(batch, reports, triages, strict=True):
            if triage["category"] != "bug_candidate":
                continue
            kinds = divergence_kinds(report)
            detail = "; ".join(
                d.get("detail", "") for d in report.get("divergences", [])
            )
            fp = fingerprint(kinds, detail, spec.get("solidity", ""))
            if fp in self.store.known_fingerprints():
                self.log(f"[finding] {spec.get('name')} is a known fingerprint")
                continue
            self.log(f"[minimize] shrinking {spec.get('name')} ...")
            small_spec = minimize(spec, report, self.executor.run, self.client)
            small_report = self.executor.run(small_spec)
            kept_spec, kept_report = (
                (small_spec, small_report)
                if divergence_kinds(small_report) >= kinds
                else (spec, report)
            )
            finding_id = self.store.add_finding(
                spec=kept_spec,
                report=kept_report,
                triage=triage,
                seed_id=seed.id,
                timing=phase_ms,
                usage=self.client.usage_since(usage_mark)["totals"],
            )
            if finding_id:
                self.log(f"[finding] NEW {finding_id}: {triage.get('summary')}")
                finding_ids.append(finding_id)
            else:
                self.log("[finding] duplicate of an existing finding")
        phase_ms["minimize_ms"] = (time.perf_counter() - t0) * 1000.0

        phase_ms["round_ms"] = (time.perf_counter() - t_round) * 1000.0
        usage = self.client.usage_since(usage_mark)["totals"]
        best = max(per_mutant, key=lambda m: _CATEGORY_RANK.get(m["category"], 0))
        return {
            "seed": seed.id,
            "name": best["name"],
            "verdict": best["verdict"],
            "category": best["category"],
            "kinds": sorted(union_kinds),
            "parent_id": parent_id,
            "origin": "mutated",
            "mutants": per_mutant,
            "mutants_invalid": len(invalid),
            "finding_id": finding_ids[0] if finding_ids else None,
            "finding_ids": finding_ids,
            "hypotheses_open": sum(
                1 for h in notebook["hypotheses"] if h["status"] == "open"
            ),
            "timing": phase_ms,
            "usage": usage,
        }

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
