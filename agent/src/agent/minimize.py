"""Verified reduction pipeline (L1): witness spec -> minimal witness.

Staged pipeline, executed in a fixed order, each stage gated on its remaining
budget (in oracle runs):

    ddmin steps -> dead-function sweep -> AST deletion -> arg shrink
    -> LLM simplify -> 1-minimality verify

All stages share one acceptance predicate (T0.2; earliest-signature equality
in "signature" mode, lenient kind-superset in "kind" mode) and one cached
RunFn. The cache lives **inside** the reducer (keyed by sha1 of the canonical
spec JSON) so `Executor.runs` stays an honest count of real oracle executions.

The run stats are recorded per stage and returned with the minimized spec;
the final verification pass re-tries every single deletion/one-notch shrink
and reports `verified_one_minimal` — the paper's 1-minimality guarantee.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from . import solast
from .ddmin import ddmin
from .executor import divergence_kinds, earliest_signature
from .llm import ChatClient, LLMError
from .prompts import load_prompt
from .shrink_args import shrink_candidates, with_arg

RunFn = Callable[[dict[str, Any]], dict[str, Any]]  # spec dict -> oracle report

_STAGE_ORDER = [
    "ddmin_steps",
    "dead_functions",
    "ast_delete",
    "arg_shrink",
    "llm_simplify",
    "verify",
]


@dataclass
class ReduceConfig:
    """Budget knobs (oracle runs per stage) and the acceptance predicate."""

    predicate: str = "signature"  # "signature" | "kind"
    step_budget: int = 40
    ast_budget: int = 200
    arg_budget: int = 40
    llm_rounds: int = 3

    @classmethod
    def from_agent_config(cls, cfg: Any) -> ReduceConfig:
        return cls(
            predicate=getattr(cfg, "predicate", "signature"),
            step_budget=getattr(cfg, "reduce_step_budget", 40),
            ast_budget=getattr(cfg, "reduce_ast_budget", 200),
            arg_budget=getattr(cfg, "reduce_arg_budget", 40),
            llm_rounds=getattr(cfg, "reduce_llm_rounds", 3),
        )


def make_predicate(
    report: dict[str, Any], mode: str = "signature"
) -> Callable[[dict[str, Any]], bool]:
    """Acceptance predicate over candidate reports.

    "signature": earliest-divergence signature equality (strict at the causal
    head). "kind": lenient kind-superset (drift experiment, T3.4). Unsigned
    (legacy) target reports in signature mode fall back to kind mode.
    """
    if mode == "signature":
        target = earliest_signature(report)
        if target is not None:

            def accept_signature(candidate: dict[str, Any]) -> bool:
                return (
                    candidate.get("verdict") == "DIVERGENCE"
                    and earliest_signature(candidate) == target
                )

            return accept_signature
    kinds = divergence_kinds(report)

    def accept_kinds(candidate: dict[str, Any]) -> bool:
        return candidate.get("verdict") == "DIVERGENCE" and kinds <= divergence_kinds(
            candidate
        )

    return accept_kinds


def _canonical(spec: dict[str, Any]) -> str:
    return json.dumps(spec, sort_keys=True, separators=(",", ":"), default=str)


class _Budget:
    """Per-stage oracle-run budget; exhausted budgets make tests fail closed."""

    def __init__(self, limit: int, stats: dict[str, int], stage: str):
        self.left = limit
        self._stats = stats
        self._stage = stage

    def charge(self) -> bool:
        """Record one real oracle run; False when the budget is exhausted."""
        if self.left <= 0:
            return False
        self.left -= 1
        self._stats[self._stage] += 1
        return True


class Reducer:
    def __init__(
        self,
        report: dict[str, Any],
        run: RunFn,
        client: ChatClient | None = None,
        config: ReduceConfig | None = None,
    ):
        self.report = report
        self.config = config or ReduceConfig()
        self.accept = make_predicate(report, self.config.predicate)
        self.client = client
        self._cache: dict[str, dict[str, Any]] = {}
        self._run = run
        self.stats: dict[str, int] = {s: 0 for s in _STAGE_ORDER}
        ed = report.get("earliest_divergence") or {}
        self.point: str | int | None = ed.get("point")
        if self.point is None:
            kinds = divergence_kinds(report)
            if kinds and kinds <= {"COMPILE_ASYMMETRY"}:
                self.point = "compile"
            elif kinds and kinds <= {"DEPLOY_MISMATCH"}:
                self.point = "deploy"

    # -- cached oracle access -------------------------------------------------

    def run(self, spec: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        """Cached oracle run; returns (report, cache_hit)."""
        key = hashlib.sha1(_canonical(spec).encode()).hexdigest()
        if key not in self._cache:
            self._cache[key] = self._run(spec)
            return self._cache[key], False
        return self._cache[key], True

    def _accepts(self, spec: dict[str, Any], budget: _Budget) -> bool:
        key = hashlib.sha1(_canonical(spec).encode()).hexdigest()
        if key in self._cache:
            return self.accept(self._cache[key])
        if not budget.charge():
            return False
        report = self._run(spec)
        self._cache[key] = report
        return self.accept(report)

    # -- stage 1: ddmin over spec steps ----------------------------------------

    def reduce_steps(self, spec: dict[str, Any]) -> dict[str, Any]:
        if self.point in ("compile", "deploy") or len(spec.get("steps", [])) <= 1:
            return spec
        budget = _Budget(self.config.step_budget, self.stats, "ddmin_steps")

        def test(steps: list[dict[str, Any]]) -> bool:
            candidate = copy.deepcopy(spec)
            candidate["steps"] = steps
            return self._accepts(candidate, budget)

        out = copy.deepcopy(spec)
        out["steps"] = ddmin(list(spec["steps"]), test)
        return out

    # -- stage 2: dead-function sweep -------------------------------------------

    @staticmethod
    def _referenced_functions(spec: dict[str, Any]) -> set[str]:
        return {s.get("function", "") for s in spec.get("steps", [])}

    def _set_source(self, spec: dict[str, Any], source: str) -> dict[str, Any]:
        out = copy.deepcopy(spec)
        out["solidity"] = source
        return out

    def dead_function_sweep(self, spec: dict[str, Any]) -> dict[str, Any]:
        source = spec.get("solidity", "")
        try:
            spans = solast.deletion_spans(
                source, keep_functions=self._referenced_functions(spec)
            )
        except solast.AstError:
            return spec  # solc cannot parse; the AST stage uses the fallback
        dead = [s for s in spans if s.kind == "FunctionDefinition"]
        if not dead:
            return spec
        budget = _Budget(1, self.stats, "dead_functions")  # one batched candidate
        candidate = source
        for span in sorted(dead, key=lambda s: -s.offset):
            candidate = solast.splice(
                candidate,
                solast.Span(span.offset, span.length, span.kind, span.name),
            )
        if not solast.parses(candidate):
            return spec
        if self._accepts(self._set_source(spec, candidate), budget):
            return self._set_source(spec, candidate)
        return spec

    # -- stage 3: AST-guided source deletion --------------------------------------

    def ast_delete(self, spec: dict[str, Any]) -> dict[str, Any]:
        source = spec.get("solidity", "")
        budget = _Budget(self.config.ast_budget, self.stats, "ast_delete")
        try:
            solast.parse_ast(source)
        except solast.AstError:
            return self._brace_fallback(spec, budget)
        keep = self._referenced_functions(spec)
        rejected: set[tuple[str, str, bytes]] = set()
        current = source
        progress = True
        while progress:
            progress = False
            try:
                spans = solast.deletion_spans(current, keep_functions=keep)
            except solast.AstError:
                break  # current source no longer parses? (accepted implies it did)
            for span in spans:
                key = (
                    span.kind,
                    span.name,
                    current.encode("utf-8")[span.offset : span.offset + span.length],
                )
                if key in rejected:
                    continue
                candidate = solast.splice(current, span)
                if candidate == current:
                    rejected.add(key)
                    continue
                if not solast.parses(candidate):  # gate 1: ~ms, no oracle run
                    rejected.add(key)
                    continue
                if self._accepts(self._set_source(spec, candidate), budget):
                    current = candidate  # gate 2 passed; offsets shift, re-parse
                    progress = True
                    break
                rejected.add(key)
        return self._set_source(spec, current)

    def _brace_fallback(self, spec: dict[str, Any], budget: _Budget) -> dict[str, Any]:
        """solc cannot parse the original (solc-rejects compile asymmetry):
        brace-aware line-chunk ddmin via the generic engine."""
        chunks = solast.brace_chunks(spec.get("solidity", ""))
        if len(chunks) <= 1:
            return spec

        def test(keep: list[str]) -> bool:
            return self._accepts(self._set_source(spec, "".join(keep)), budget)

        return self._set_source(spec, "".join(ddmin(chunks, test)))

    # -- stage 4: argument shrinking ----------------------------------------------

    def arg_shrink(self, spec: dict[str, Any]) -> dict[str, Any]:
        if self.point in ("compile", "deploy") or not spec.get("steps"):
            return spec
        budget = _Budget(self.config.arg_budget, self.stats, "arg_shrink")
        current = spec
        progress = True
        while progress:
            progress = False
            for i, j, value in shrink_candidates(current):
                candidate = with_arg(current, i, j, value)
                if self._accepts(candidate, budget):
                    current = candidate
                    progress = True
                    break
        return current

    # -- stage 5: LLM simplify (demoted, last) -------------------------------------

    def llm_simplify(self, spec: dict[str, Any]) -> dict[str, Any]:
        """LLM-guided shrinking on the residual (deletion cannot simplify
        expressions or narrow types). Routed to the flash tier via the
        "minimize" stage tag. The must-get-smaller stop rule stays."""
        if self.client is None or self.config.llm_rounds <= 0:
            return spec
        budget = _Budget(self.config.llm_rounds, self.stats, "llm_simplify")
        best = spec
        diverging_fns = sorted(
            {
                s["function"]
                for s in self.report.get("steps", [])
                if s.get("divergences")
            }
        )
        for _ in range(self.config.llm_rounds):
            system = (
                "You minimize Solidity reproducers for compiler bug reports. "
                "You reply with a single JSON object and nothing else."
            )
            user = load_prompt("minimize").substitute(
                functions=", ".join(diverging_fns) or "(unknown)",
                contract=best["contract"],
                divergences_json=json.dumps(
                    self.report.get("divergences", []), indent=2
                ),
                source=best["solidity"],
            )
            try:
                shrunk = self.client.chat_json(
                    system, user, validate=_validate_shrunk, stage="minimize"
                )
            except LLMError:
                break
            if len(shrunk["solidity"]) >= len(best["solidity"]):
                break  # model failed to shrink; stop spending oracle runs
            candidate = copy.deepcopy(best)
            candidate["solidity"] = shrunk["solidity"]
            if self._accepts(candidate, budget):
                best = candidate
            else:
                break  # divergence lost; the current best is minimal enough
        return best

    # -- stage 6: verified 1-minimality ---------------------------------------------

    def verify_one_minimal(self, spec: dict[str, Any]) -> tuple[bool, int]:
        """Re-try every single deletion / one-notch shrink on the final witness."""
        budget = _Budget(1 << 30, self.stats, "verify")  # exhaustive by design
        residual = 0
        # each step
        if self.point not in ("compile", "deploy"):
            for i in range(len(spec.get("steps", []))):
                candidate = copy.deepcopy(spec)
                candidate["steps"].pop(i)
                if self._accepts(candidate, budget):
                    residual += 1
        # each remaining AST node (gate-1 filtered)
        keep = self._referenced_functions(spec)
        try:
            spans = solast.deletion_spans(spec.get("solidity", ""), keep_functions=keep)
        except solast.AstError:
            spans = []
        for span in spans:
            candidate = solast.splice(spec.get("solidity", ""), span)
            if candidate == spec.get("solidity", "") or not solast.parses(candidate):
                continue
            if self._accepts(self._set_source(spec, candidate), budget):
                residual += 1
        # each one-notch arg shrink
        if self.point not in ("compile", "deploy"):
            for i, j, value in shrink_candidates(spec):
                if self._accepts(with_arg(spec, i, j, value), budget):
                    residual += 1
        return residual == 0, residual

    # -- pipeline -------------------------------------------------------------------

    def reduce(self, spec: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        """Run the full pipeline; returns (minimized spec, minimality record)."""
        out = copy.deepcopy(spec)
        out = self.reduce_steps(out)
        out = self.dead_function_sweep(out)
        out = self.ast_delete(out)
        out = self.arg_shrink(out)
        out = self.llm_simplify(out)
        verified, residual = self.verify_one_minimal(out)
        minimality = {
            "verified_one_minimal": verified,
            "residual_deletable": residual,
            "oracle_runs": sum(self.stats.values()),
            "stages": dict(self.stats),
        }
        return out, minimality


def _validate_shrunk(d: dict[str, Any]) -> list[str]:
    src = d.get("solidity")
    if not isinstance(src, str) or "contract" not in src:
        return ["missing 'solidity' source string"]
    return []


def minimize(
    spec: dict[str, Any],
    report: dict[str, Any],
    run: RunFn,
    client: ChatClient | None = None,
    *,
    config: ReduceConfig | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Minimize a bug-candidate spec; returns (spec, minimality record)."""
    return Reducer(report, run, client, config).reduce(spec)
