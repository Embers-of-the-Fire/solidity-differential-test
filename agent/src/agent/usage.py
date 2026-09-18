"""LLM usage tracing: token counts, dollar cost and latency per call.

Every chat-completion call (including retried and failed attempts) is recorded
as one JSON object per line in ``<findings_dir>/llm_usage.jsonl``. The raw
``usage`` object returned by the server is stored verbatim (``usage_raw``) so
provider-specific fields — cached-token splits, llama.cpp ``timings``, vLLM
extensions — are never lost.

Cost is computed from configurable prices (USD per 1M tokens). Local servers
default to 0.0, which keeps ``cost_usd`` at 0 while token counts stay exact.
Cache-hit tokens are priced separately: servers that report
``usage.prompt_tokens_details.cached_tokens`` (OpenAI, vLLM) get the cached
rate; servers that do not report the split leave ``cached_prompt_tokens`` null
and all input tokens are billed at the full input rate.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class Pricing:
    """USD per 1M tokens. Defaults are free (local inference)."""

    input_per_1m: float = 0.0
    output_per_1m: float = 0.0
    cached_input_per_1m: float | None = None  # None -> same as input_per_1m

    def cost_usd(
        self, prompt_tokens: int, cached_prompt_tokens: int, completion_tokens: int
    ) -> float:
        cached_rate = (
            self.input_per_1m
            if self.cached_input_per_1m is None
            else self.cached_input_per_1m
        )
        uncached = max(0, prompt_tokens - cached_prompt_tokens)
        return (
            uncached * self.input_per_1m
            + cached_prompt_tokens * cached_rate
            + completion_tokens * self.output_per_1m
        ) / 1_000_000


def extract_usage(usage_raw: Any) -> dict[str, Any]:
    """Normalize an OpenAI-compatible ``usage`` object into flat fields."""
    if usage_raw is None:
        return {
            "prompt_tokens": None,
            "cached_prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
            "usage_raw": None,
        }
    if hasattr(usage_raw, "model_dump"):
        usage_raw = usage_raw.model_dump()
    details = usage_raw.get("prompt_tokens_details") or {}
    return {
        "prompt_tokens": usage_raw.get("prompt_tokens"),
        "cached_prompt_tokens": details.get("cached_tokens"),
        "completion_tokens": usage_raw.get("completion_tokens"),
        "total_tokens": usage_raw.get("total_tokens"),
        "usage_raw": usage_raw,
    }


def _empty_totals() -> dict[str, Any]:
    return {
        "calls": 0,
        "errors": 0,
        "prompt_tokens": 0,
        "cached_prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "cost_usd": 0.0,
        "latency_ms": 0.0,
    }


def _accumulate(acc: dict[str, Any], record: dict[str, Any]) -> None:
    acc["calls"] += 1
    acc["errors"] += 1 if record.get("error") else 0
    acc["latency_ms"] += record.get("latency_ms") or 0.0
    for key in (
        "prompt_tokens",
        "cached_prompt_tokens",
        "completion_tokens",
        "total_tokens",
    ):
        acc[key] += record.get(key) or 0
    acc["cost_usd"] += record.get("cost_usd") or 0.0


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate usage records: totals plus a per-stage breakdown."""
    totals = _empty_totals()
    stages: dict[str, dict[str, Any]] = {}
    for rec in records:
        _accumulate(totals, rec)
        stage_acc = stages.setdefault(rec.get("stage") or "unknown", _empty_totals())
        _accumulate(stage_acc, rec)
    totals["avg_latency_ms"] = (
        totals["latency_ms"] / totals["calls"] if totals["calls"] else 0.0
    )
    for stage_acc in stages.values():
        n = stage_acc["calls"]
        stage_acc["avg_latency_ms"] = stage_acc["latency_ms"] / n if n else 0.0
    return {"totals": totals, "per_stage": dict(sorted(stages.items()))}


class UsageTracker:
    """Collects usage records in memory and write-through appends to JSONL."""

    def __init__(self, log_path: str | Path | None, pricing: Pricing | None = None):
        self.log_path = Path(log_path) if log_path else None
        self.pricing = pricing or Pricing()
        self.records: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        # stage/attempt context set by chat_json for the next chat() call
        self._stage = "unknown"
        self._attempt = 0

    def set_context(self, stage: str, attempt: int) -> None:
        self._stage = stage
        self._attempt = attempt

    def record(
        self,
        *,
        model: str,
        temperature: float,
        latency_ms: float,
        usage_raw: Any = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        fields = extract_usage(usage_raw)
        cost: float | None = None
        if (
            fields["prompt_tokens"] is not None
            and fields["completion_tokens"] is not None
        ):
            cost = self.pricing.cost_usd(
                fields["prompt_tokens"],
                fields["cached_prompt_tokens"] or 0,
                fields["completion_tokens"],
            )
        rec: dict[str, Any] = {
            "ts": time.time(),
            "stage": self._stage,
            "attempt": self._attempt,
            "model": model,
            "temperature": temperature,
            "latency_ms": latency_ms,
            "prompt_tokens": fields["prompt_tokens"],
            "cached_prompt_tokens": fields["cached_prompt_tokens"],
            "completion_tokens": fields["completion_tokens"],
            "total_tokens": fields["total_tokens"],
            "cost_usd": cost,
            "usage_raw": fields["usage_raw"],
            "error": error,
        }
        with self._lock:
            self.records.append(rec)
            if self.log_path:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                with self.log_path.open("a") as f:
                    f.write(json.dumps(rec) + "\n")
        return rec

    def marker(self) -> int:
        """Current record count; use with records_since() for deltas."""
        with self._lock:
            return len(self.records)

    def records_since(self, marker: int) -> list[dict[str, Any]]:
        with self._lock:
            return list(self.records[marker:])

    def totals(self) -> dict[str, Any]:
        with self._lock:
            return summarize(self.records)

    @staticmethod
    def zero_totals() -> dict[str, Any]:
        """Totals shape for clients that do not track usage (fakes)."""
        return {"totals": _empty_totals(), "per_stage": {}}


def summarize_jsonl(path: str | Path) -> dict[str, Any]:
    """Aggregate a persisted llm_usage.jsonl (for the `cost` CLI)."""
    p = Path(path)
    if not p.exists():
        return summarize([])
    records = [
        json.loads(line) for line in p.read_text().strip().splitlines() if line.strip()
    ]
    return summarize(records)


class NoUsage:
    """Mixin for fake/test chat clients: zero usage accounting."""

    def usage_marker(self) -> int:
        return 0

    def usage_since(self, marker: int) -> dict[str, Any]:
        return summarize([])

    def usage_totals(self) -> dict[str, Any]:
        return summarize([])
