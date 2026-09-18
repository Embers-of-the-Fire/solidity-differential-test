"""OpenAI-compatible LLM client with a validate-and-repair loop.

Local models frequently wrap JSON in prose or markdown fences, or emit
slightly invalid JSON. `chat_json` therefore extracts the JSON payload,
validates it with a caller-supplied function, and feeds errors back to the
model for a bounded number of repair attempts.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from typing import Any, Protocol

from openai import OpenAI, OpenAIError

from .config import AgentConfig
from .usage import UsageTracker

_FENCE_RE = re.compile(r"```(?:json)?\s*\n(.*?)```", re.DOTALL)


class LLMError(Exception):
    """Unrecoverable LLM interaction failure (API down, repair budget spent)."""


class ChatClient(Protocol):
    """Structural type for anything the agent can query (real or fake)."""

    calls: int

    def budget_left(self) -> int: ...

    def usage_totals(self) -> dict[str, Any]: ...

    def usage_since(self, marker: int) -> dict[str, Any]: ...

    def usage_marker(self) -> int: ...

    def chat_json(
        self,
        system: str,
        user: str,
        *,
        validate: Callable[[dict[str, Any]], list[str]] | None = None,
        max_attempts: int = 3,
        stage: str = "unknown",
    ) -> dict[str, Any]: ...


def extract_json(text: str) -> dict[str, Any]:
    """Pull a JSON object out of model output (fenced or raw)."""
    candidates = [m.group(1) for m in _FENCE_RE.finditer(text)]
    candidates.append(text.strip())
    # last resort: outermost brace span
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        candidates.append(text[start : end + 1])
    for cand in candidates:
        try:
            obj = json.loads(cand)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    raise LLMError(f"no JSON object found in model output: {text[:200]!r}")


class LLMClient:
    """Thin wrapper around an OpenAI-compatible chat-completions endpoint."""

    def __init__(self, cfg: AgentConfig):
        cfg.check_llm()
        self.cfg = cfg
        self.calls = 0
        self._client = OpenAI(
            base_url=cfg.base_url, api_key=cfg.api_key, timeout=cfg.llm_timeout_s
        )
        self.usage = UsageTracker(
            cfg.findings_dir / "llm_usage.jsonl", pricing=cfg.pricing()
        )

    def budget_left(self) -> int:
        return self.cfg.llm_calls_budget - self.calls

    def usage_totals(self) -> dict[str, Any]:
        return self.usage.totals()

    def usage_marker(self) -> int:
        return self.usage.marker()

    def usage_since(self, marker: int) -> dict[str, Any]:
        from .usage import summarize

        return summarize(self.usage.records_since(marker))

    def chat(self, system: str, user: str, *, max_retries: int = 3) -> str:
        """One chat completion with retries on transient API errors."""
        if self.budget_left() <= 0:
            raise LLMError("LLM call budget exhausted")
        last_err: Exception | None = None
        for _ in range(max_retries):
            t0 = time.perf_counter()
            try:
                self.calls += 1
                resp = self._client.chat.completions.create(
                    model=self.cfg.model,
                    temperature=self.cfg.temperature,
                    max_tokens=self.cfg.max_tokens,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                )
                latency_ms = (time.perf_counter() - t0) * 1000.0
                self.usage.record(
                    model=self.cfg.model,
                    temperature=self.cfg.temperature,
                    latency_ms=latency_ms,
                    usage_raw=getattr(resp, "usage", None),
                )
                content = resp.choices[0].message.content
                if not content:
                    raise LLMError("model returned empty content")
                return content
            except OpenAIError as e:
                last_err = e
                self.usage.record(
                    model=self.cfg.model,
                    temperature=self.cfg.temperature,
                    latency_ms=(time.perf_counter() - t0) * 1000.0,
                    error=f"{type(e).__name__}: {e}",
                )
        raise LLMError(f"LLM API failed after {max_retries} attempts: {last_err}")

    def chat_json(
        self,
        system: str,
        user: str,
        *,
        validate: Callable[[dict[str, Any]], list[str]] | None = None,
        max_attempts: int = 3,
        stage: str = "unknown",
    ) -> dict[str, Any]:
        """Chat until the model returns JSON passing `validate` (or budget ends).

        `validate` returns a list of human-readable problems (empty = valid);
        problems are fed back to the model as a repair instruction.
        """
        feedback = ""
        last_err = ""
        for attempt in range(max_attempts):
            self.usage.set_context(stage, attempt)
            text = self.chat(system, user + feedback)
            try:
                obj = extract_json(text)
            except LLMError as e:
                last_err = str(e)
                feedback = (
                    "\n\nYour previous reply was not a single JSON object. "
                    "Reply with ONLY one JSON object, no prose, no markdown fences."
                )
                continue
            problems = validate(obj) if validate else []
            if not problems:
                return obj
            last_err = "; ".join(problems)
            feedback = (
                "\n\nYour previous JSON was invalid:\n"
                + "\n".join(f"- {p}" for p in problems)
                + "\nFix it and reply with ONLY the corrected JSON object."
            )
        raise LLMError(
            f"model did not produce valid JSON after {max_attempts} attempts: {last_err}"
        )
