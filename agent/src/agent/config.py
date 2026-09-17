"""Agent configuration.

The LLM endpoint is deliberately a placeholder: the first `hunt` run fails
fast with a clear message until you point it at your local OpenAI-compatible
server. Configure via environment variables:

    AGENT_LLM_BASE_URL   e.g. http://127.0.0.1:8080/v1   (llama.cpp / vLLM / Ollama)
    AGENT_LLM_MODEL      model name the server expects
    AGENT_LLM_API_KEY    optional; most local servers ignore it (default: "local")
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

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
    parallel: int = 4
    findings_dir: Path = field(default_factory=lambda: Path("findings"))

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
    parallel: int | None = None,
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
    if parallel is not None:
        cfg.parallel = parallel
    return cfg
