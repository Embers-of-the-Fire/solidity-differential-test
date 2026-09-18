"""End-to-end smoke test: real oracle run driven through the agent pipeline.

Uses a canned spec that exercises a documented divergence (gasleft return
value), so triage is handled by the deterministic rules and NO LLM calls are
needed. Requires the flake devshell binaries (solc, solang, anvil,
substrate-contracts-node). Run inside `nix develop`:

    uv run --package solidity-diff-agent pytest agent/tests/
"""

import pytest

from agent.config import AgentConfig
from agent.executor import Executor
from agent.loop import HuntLoop
from agent.store import FindingStore
from agent.triage import triage_report
from agent.usage import NoUsage

GASLEFT_SPEC = {
    "name": "e2e-gasleft",
    "solidity": (
        "// SPDX-License-Identifier: MIT\n"
        "pragma solidity >=0.8.0;\n"
        "contract g {\n"
        "    function gl() public view returns (uint256) { return gasleft(); }\n"
        "}\n"
    ),
    "contract": "g",
    "steps": [{"action": "query", "function": "gl"}],
}


class NoLLM(NoUsage):
    """Asserts the pipeline never needs the LLM for this canned probe."""

    calls = 0

    def budget_left(self):
        return 0

    def chat_json(self, system, user, **kwargs):
        raise AssertionError("LLM must not be called for rule-covered triage")


@pytest.mark.slow
def test_e2e_known_divergence_triaged_without_llm(tmp_path):
    executor = Executor(parallel=1)
    try:
        report = executor.run(dict(GASLEFT_SPEC))
    finally:
        executor.close()
    assert report["verdict"] == "DIVERGENCE", report.get("error")
    assert {d["kind"] for d in report["divergences"]} == {"RETURN_MISMATCH"}

    triage = triage_report(NoLLM(), dict(GASLEFT_SPEC), report)
    assert triage["category"] == "known_semantic"
    assert triage.get("rule_based")


@pytest.mark.slow
def test_e2e_hunt_loop_one_round(tmp_path):
    """One full loop round: canned generation, real oracle, rule triage."""

    class CannedLLM(NoUsage):
        calls = 0

        def budget_left(self):
            return 1

        def chat_json(
            self, system, user, *, validate=None, max_attempts=3, stage="unknown"
        ):
            self.calls += 1
            if "hypothesis notebook" in system:
                return {"ops": [], "reasoning": "documented difference, nothing new"}
            spec = dict(GASLEFT_SPEC)
            if validate:
                assert validate(spec) == []
            return spec

    cfg = AgentConfig(findings_dir=tmp_path, llm_calls_budget=2, oracle_runs_budget=2)
    loop = HuntLoop(
        cfg,
        client=CannedLLM(),
        executor=Executor(parallel=1),
        store=FindingStore(tmp_path),
        rng_seed=0,
        log=lambda *_: None,
    )
    try:
        summary = loop.hunt(max_rounds=1)
    finally:
        loop.executor.close()
    assert summary["rounds"] == 1
    assert summary["new_findings"] == 0  # known semantic, not a bug candidate
    probe = loop.store.recent_probes(1)[0]
    assert probe["verdict"] == "DIVERGENCE"
    assert probe["category"] == "known_semantic"
