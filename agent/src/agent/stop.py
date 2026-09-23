"""Stop policy for the hunt loop: budget stops plus saturation stop.

Owned by the caller (CLI / evaluation harness), not hardwired in `HuntLoop`,
so ablation runs can impose per-configuration policies. The loop evaluates
`policy.check(state)` after each round and reports the returned key as the
machine-readable `stop_reason`:

    round_limit     max rounds reached
    oracle_budget   oracle run budget exhausted
    llm_budget      LLM call budget exhausted
    saturation      no new signal in the last K rounds
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

STOP_REASONS = ("round_limit", "oracle_budget", "llm_budget", "saturation")


@dataclass
class LoopState:
    """Cumulative counters the policy inspects. Updated by `HuntLoop.hunt`."""

    rounds: int = 0
    oracle_runs: int = 0
    llm_calls: int = 0
    signal_history: deque[bool] = field(default_factory=deque)


@dataclass
class StopPolicy:
    """None on any field disables that stop condition."""

    max_rounds: int | None = None
    oracle_runs_budget: int | None = None
    llm_calls_budget: int | None = None
    saturation_window: int | None = None  # K; None disables the saturation stop

    def check(self, state: LoopState) -> str | None:
        """Return a stop-reason key, or None to keep hunting."""
        if self.max_rounds is not None and state.rounds >= self.max_rounds:
            return "round_limit"
        if (
            self.oracle_runs_budget is not None
            and state.oracle_runs >= self.oracle_runs_budget
        ):
            return "oracle_budget"
        if (
            self.llm_calls_budget is not None
            and state.llm_calls >= self.llm_calls_budget
        ):
            return "llm_budget"
        if self.saturation_window is not None:
            window = list(state.signal_history)[-self.saturation_window :]
            if len(window) == self.saturation_window and not any(window):
                return "saturation"
        return None
