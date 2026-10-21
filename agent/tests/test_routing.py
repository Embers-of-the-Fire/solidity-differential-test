"""Unit tests for per-stage LLM routing (T2.4): stage -> tier -> model mapping
and the tier field on usage records."""

from agent.config import AgentConfig
from agent.llm import model_for_stage, tier_for_stage
from agent.usage import UsageTracker


def test_stage_tier_mapping():
    for stage in ("generate", "triage", "reflect"):
        assert tier_for_stage(stage) == "reasoning"
    for stage in ("mutate", "minimize"):
        assert tier_for_stage(stage) == "flash"
    assert tier_for_stage("unknown") == "reasoning"


def test_model_routing_single_model_default():
    cfg = AgentConfig(model="k3")
    assert model_for_stage(cfg, "generate") == "k3"
    assert model_for_stage(cfg, "minimize") == "k3"  # light defaults to model


def test_model_routing_two_model_split():
    cfg = AgentConfig(model="k3", model_light="deepseek-flash")
    assert model_for_stage(cfg, "triage") == "k3"
    assert model_for_stage(cfg, "mutate") == "deepseek-flash"


def test_usage_records_carry_tier(tmp_path):
    tracker = UsageTracker(tmp_path / "llm_usage.jsonl")
    tracker.record(model="m", temperature=0.0, latency_ms=1.0, tier="flash")
    line = (tmp_path / "llm_usage.jsonl").read_text().strip()
    import json

    assert json.loads(line)["tier"] == "flash"


def test_load_config_reads_light_model_env(monkeypatch):
    from agent.config import load_config

    monkeypatch.setenv("AGENT_LLM_MODEL", "k3")
    monkeypatch.setenv("AGENT_LLM_MODEL_LIGHT", "deepseek-flash")
    cfg = load_config()
    assert cfg.model_light == "deepseek-flash"
    monkeypatch.delenv("AGENT_LLM_MODEL_LIGHT")
    cfg = load_config()
    assert cfg.model_light == "k3"
