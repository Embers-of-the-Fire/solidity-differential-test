import pytest

from agent.config import AgentConfig, AgentConfigError, load_config


def test_placeholder_config_fails_fast():
    cfg = AgentConfig()
    with pytest.raises(AgentConfigError, match="AGENT_LLM_BASE_URL"):
        cfg.check_llm()


def test_env_override_makes_config_valid(monkeypatch):
    monkeypatch.setenv("AGENT_LLM_BASE_URL", "http://127.0.0.1:8080/v1")
    monkeypatch.setenv("AGENT_LLM_MODEL", "some-model")
    cfg = load_config()
    cfg.check_llm()  # must not raise
    assert cfg.base_url == "http://127.0.0.1:8080/v1"
    assert cfg.model == "some-model"


def test_cli_overrides(tmp_path):
    cfg = load_config(findings_dir=tmp_path, llm_calls=7, oracle_runs=9, parallel=2)
    assert cfg.findings_dir == tmp_path
    assert cfg.llm_calls_budget == 7
    assert cfg.oracle_runs_budget == 9
    assert cfg.parallel == 2
