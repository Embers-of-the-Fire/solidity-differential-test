"""Elapsed-time tracing helpers.

Timing is recorded for traceability and cost analysis but is **never** part of
the oracle comparison (same rule as block metadata: chains differ in cadence
and fee models by design).
"""

from __future__ import annotations

import time
from datetime import UTC, datetime


def now_epoch() -> float:
    return time.time()


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


class Timer:
    """Context manager measuring wall-clock elapsed milliseconds."""

    def __init__(self):
        self.elapsed_ms: float | None = None
        self._t0: float = 0.0

    def __enter__(self) -> Timer:
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.elapsed_ms = (time.perf_counter() - self._t0) * 1000.0
