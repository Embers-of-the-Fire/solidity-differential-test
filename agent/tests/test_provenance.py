import json

from agent import provenance
from agent.config import AgentConfig


def test_campaign_metadata_is_complete_and_stable(tmp_path, monkeypatch):
    monkeypatch.setattr(provenance, "_run_version", lambda command: "test-version")
    monkeypatch.setattr(provenance, "_git_rev", lambda: "deadbeef")
    cfg = AgentConfig(findings_dir=tmp_path, api_key="do-not-record")
    path = provenance.write_campaign_metadata(tmp_path, cfg, extra={"rng_seed": 7})
    first = json.loads(path.read_text())
    assert first["git_rev"] == "deadbeef"
    assert first["config"]["execution_mode"] == "on-chain"
    assert "api_key" not in first["config"]
    assert first["seed_files_sha256"]
    assert first["rng_seed"] == 7
    assert set(first["tool_versions"]) == {
        "solc",
        "solang",
        "anvil",
        "substrate-contracts-node",
    }

    provenance.write_campaign_metadata(
        tmp_path, AgentConfig(findings_dir=tmp_path), extra={"rng_seed": 99}
    )
    assert json.loads(path.read_text()) == first
