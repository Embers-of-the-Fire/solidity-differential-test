"""Agent configuration.

The LLM endpoint is deliberately a placeholder: the first `hunt` run fails
fast with a clear message until you point it at your local OpenAI-compatible
server. Configure via environment variables:

    AGENT_LLM_BASE_URL   e.g. http://127.0.0.1:8080/v1   (llama.cpp / vLLM / Ollama)
    AGENT_LLM_MODEL      model name the server expects
    AGENT_LLM_API_KEY    optional; most local servers ignore it (default: "local")

Usage cost is computed from optional prices (USD per 1M tokens, default 0.0):

    AGENT_LLM_PRICE_INPUT_PER_1M         uncached input (prompt) tokens
    AGENT_LLM_PRICE_CACHED_INPUT_PER_1M  cached input tokens (default: same as input)
    AGENT_LLM_PRICE_OUTPUT_PER_1M        output (completion) tokens
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .usage import Pricing

PLACEHOLDER_BASE_URL = "http://REPLACE-ME.invalid/v1"
PLACEHOLDER_MODEL = "REPLACE-ME"


class AgentConfigError(Exception):
    """Raised when the agent is not configured correctly (e.g. placeholder endpoint)."""


@dataclass
class AgentConfig:
    base_url: str = PLACEHOLDER_BASE_URL
    model: str = PLACEHOLDER_MODEL
    api_key: str = "local"
    temperature: float = 1.0
    max_tokens: int = 4096
    llm_timeout_s: float = 180.0
    llm_calls_budget: int = 50
    oracle_runs_budget: int = 100
    saturation_window: int = 10
    parallel: int = 4
    p_mutate: float = 0.7  # 0.0 reproduces the generation-only baseline loop
    prog_mutants_per_round: int = 4  # free programmatic mutants per mutation round
    llm_mutants_per_round: int = 4  # mutants requested in the single batch LLM call
    prog_ops_per_mutant: int = 2  # operator applications per programmatic mutant
    reflect: str = "always"  # "always" | "never" (feedback ablation axis)
    admission: str = (
        "on"  # "on" | "off" (off = admit everything, random-restart control)
    )
    findings_dir: Path = field(default_factory=lambda: Path("findings"))
    seeds_dir: Path | None = None  # None -> packaged agent/seeds/
    price_input_per_1m: float = 0.0
    price_cached_input_per_1m: float | None = None  # None -> same as input
    price_output_per_1m: float = 0.0

    def pricing(self) -> Pricing:
        return Pricing(
            input_per_1m=self.price_input_per_1m,
            output_per_1m=self.price_output_per_1m,
            cached_input_per_1m=self.price_cached_input_per_1m,
        )

    def check_llm(self) -> None:
        """Fail fast if the endpoint is still the placeholder."""
        problems = []
        if self.base_url == PLACEHOLDER_BASE_URL or "REPLACE-ME" in self.base_url:
            problems.append("AGENT_LLM_BASE_URL is not set (placeholder)")
        if self.model == PLACEHOLDER_MODEL or "REPLACE-ME" in self.model:
            problems.append("AGENT_LLM_MODEL is not set (placeholder)")
        if problems:
            raise AgentConfigError(
                "LLM endpoint not configured: "
                + "; ".join(problems)
                + ". Point the agent at your local OpenAI-compatible server, e.g.\n"
                "  export AGENT_LLM_BASE_URL=http://127.0.0.1:8080/v1\n"
                "  export AGENT_LLM_MODEL=<your-model-name>\n"
                "(llama.cpp `llama-server`, vLLM `vllm serve` and Ollama all "
                "speak the OpenAI chat-completions API.)"
            )


def load_config(
    *,
    findings_dir: str | Path | None = None,
    llm_calls: int | None = None,
    oracle_runs: int | None = None,
    saturation_window: int | None = None,
    parallel: int | None = None,
    p_mutate: float | None = None,
    prog_mutants_per_round: int | None = None,
    llm_mutants_per_round: int | None = None,
    prog_ops_per_mutant: int | None = None,
    reflect: str | None = None,
    admission: str | None = None,
    seeds_dir: str | Path | None = None,
) -> AgentConfig:
    cfg = AgentConfig(
        base_url=os.environ.get("AGENT_LLM_BASE_URL", PLACEHOLDER_BASE_URL),
        model=os.environ.get("AGENT_LLM_MODEL", PLACEHOLDER_MODEL),
        api_key=os.environ.get("AGENT_LLM_API_KEY", "local"),
    )
    if findings_dir is not None:
        cfg.findings_dir = Path(findings_dir)
    if llm_calls is not None:
        cfg.llm_calls_budget = llm_calls
    if oracle_runs is not None:
        cfg.oracle_runs_budget = oracle_runs
    if saturation_window is not None:
        cfg.saturation_window = saturation_window
    if parallel is not None:
        cfg.parallel = parallel
    if p_mutate is not None:
        cfg.p_mutate = p_mutate
    if prog_mutants_per_round is not None:
        cfg.prog_mutants_per_round = prog_mutants_per_round
    if llm_mutants_per_round is not None:
        cfg.llm_mutants_per_round = llm_mutants_per_round
    if prog_ops_per_mutant is not None:
        cfg.prog_ops_per_mutant = prog_ops_per_mutant
    if reflect is not None:
        if reflect not in ("always", "never"):
            raise AgentConfigError(
                f"reflect must be 'always' or 'never', got {reflect!r}"
            )
        cfg.reflect = reflect
    if admission is not None:
        if admission not in ("on", "off"):
            raise AgentConfigError(
                f"admission must be 'on' or 'off', got {admission!r}"
            )
        cfg.admission = admission
    if seeds_dir is not None:
        cfg.seeds_dir = Path(seeds_dir)
    cfg.price_input_per_1m = float(os.environ.get("AGENT_LLM_PRICE_INPUT_PER_1M", 0.0))
    cached = os.environ.get("AGENT_LLM_PRICE_CACHED_INPUT_PER_1M")
    cfg.price_cached_input_per_1m = float(cached) if cached else None
    cfg.price_output_per_1m = float(
        os.environ.get("AGENT_LLM_PRICE_OUTPUT_PER_1M", 0.0)
    )
    return cfg
