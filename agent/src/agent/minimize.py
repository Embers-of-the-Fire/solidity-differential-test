"""Minimization of bug-candidate reproducers.

Two phases, each candidate verified by an oracle run:

1. Step pruning (delta debugging): greedily drop spec steps while the same
   divergence kinds persist.
2. Source shrinking: the LLM rewrites the contract smaller; each candidate is
   re-run and accepted only if the same divergence kinds survive.

Both phases are budget-bound via `max_oracle_runs`.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from typing import Any

from .executor import divergence_kinds
from .llm import ChatClient, LLMError
from .prompts import load_prompt

RunFn = Callable[[dict[str, Any]], dict[str, Any]]  # spec dict -> oracle report


def _kinds_survive(report: dict[str, Any], target_kinds: set[str]) -> bool:
    return report.get("verdict") == "DIVERGENCE" and target_kinds <= divergence_kinds(
        report
    )


def minimize_steps(
    spec: dict[str, Any], target_kinds: set[str], run: RunFn, max_oracle_runs: int = 10
) -> dict[str, Any]:
    """Greedily remove steps while the target divergence kinds persist."""
    best = copy.deepcopy(spec)
    runs = 0
    i = 0
    while i < len(best["steps"]) and runs < max_oracle_runs:
        if len(best["steps"]) <= 1:
            break
        candidate = copy.deepcopy(best)
        candidate["steps"].pop(i)
        report = run(candidate)
        runs += 1
        if _kinds_survive(report, target_kinds):
            best = candidate  # keep removal; re-check same index
        else:
            i += 1  # the removed step is needed; move on
    return best


def _validate_shrunk(d: dict[str, Any]) -> list[str]:
    src = d.get("solidity")
    if not isinstance(src, str) or "contract" not in src:
        return ["missing 'solidity' source string"]
    return []


def minimize_source(
    spec: dict[str, Any],
    report: dict[str, Any],
    run: RunFn,
    client: ChatClient,
    max_rounds: int = 3,
) -> dict[str, Any]:
    """LLM-guided contract shrinking, verified against the oracle."""
    best = copy.deepcopy(spec)
    target_kinds = divergence_kinds(report)
    diverging_fns = sorted(
        {s["function"] for s in report.get("steps", []) if s.get("divergences")}
    )
    for _ in range(max_rounds):
        system = (
            "You minimize Solidity reproducers for compiler bug reports. "
            "You reply with a single JSON object and nothing else."
        )
        user = load_prompt("minimize").substitute(
            functions=", ".join(diverging_fns) or "(unknown)",
            contract=best["contract"],
            divergences_json=json.dumps(report.get("divergences", []), indent=2),
            source=best["solidity"],
        )
        try:
            shrunk = client.chat_json(
                system, user, validate=_validate_shrunk, stage="minimize"
            )
        except LLMError:
            break
        if len(shrunk["solidity"]) >= len(best["solidity"]):
            break  # model failed to shrink; stop spending oracle runs
        candidate = copy.deepcopy(best)
        candidate["solidity"] = shrunk["solidity"]
        candidate_report = run(candidate)
        if _kinds_survive(candidate_report, target_kinds):
            best = candidate
        else:
            break  # divergence lost; the current best is minimal enough
    return best


def minimize(
    spec: dict[str, Any],
    report: dict[str, Any],
    run: RunFn,
    client: ChatClient,
    *,
    max_step_runs: int = 10,
    max_source_rounds: int = 3,
) -> dict[str, Any]:
    target_kinds = divergence_kinds(report)
    shrunk_steps = minimize_steps(
        spec, target_kinds, run, max_oracle_runs=max_step_runs
    )
    return minimize_source(
        shrunk_steps, report, run, client, max_rounds=max_source_rounds
    )
