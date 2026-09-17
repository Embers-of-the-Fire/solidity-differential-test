"""Integration test of the full hunt loop with a fake LLM and a scripted oracle.

No chain nodes, no network: proves generate -> run -> triage -> minimize ->
dedup plumbing end to end.
"""

import json

from agent.config import AgentConfig
from agent.llm import LLMError
from agent.loop import HuntLoop
from agent.store import FindingStore

CANNED_SOURCE = """// SPDX-License-Identifier: MIT
pragma solidity >=0.8.0;
contract broken {
    function add(uint8 a, uint8 b) public pure returns (uint16) { return a + b; }
}
"""

CANNED_SPEC = {
    "name": "canned-add",
    "solidity": CANNED_SOURCE,
    "contract": "broken",
    "steps": [{"action": "query", "function": "add", "args": [200, 100]}],
}

DIVERGENT_REPORT = {
    "name": "canned-add",
    "verdict": "DIVERGENCE",
    "divergences": [
        {
            "kind": "RETURN_MISMATCH",
            "step": 0,
            "detail": "dry-run return values differ",
            "evm": 44,
            "polkadot": 300,
        }
    ],
    "steps": [
        {"index": 0, "function": "add", "divergences": [{"kind": "RETURN_MISMATCH"}]}
    ],
    "tool_versions": {
        "solc": "x",
        "solang": "y",
        "anvil": "z",
        "substrate-contracts-node": "w",
    },
}

PASS_REPORT = {"name": "canned-add", "verdict": "PASS", "divergences": []}


class FakeLLM:
    def __init__(self, budget=100):
        self.calls = 0
        self.budget = budget
        self.prompts: list[tuple[str, str]] = []

    def budget_left(self):
        return self.budget - self.calls

    def chat_json(self, system, user, *, validate=None, max_attempts=3):
        if self.budget_left() <= 0:
            raise LLMError("LLM call budget exhausted")
        self.calls += 1
        self.prompts.append((system, user))
        if "differential-testing probes" in system:
            return dict(CANNED_SPEC)
        if "triage" in system:
            return {
                "category": "bug_candidate",
                "confidence": "high",
                "rationale": "uint8 addition wraps on EVM but not on solang",
                "blame": "solang",
                "summary": "uint8 arithmetic overflow not checked/wrapped identically",
            }
        if "hypothesis notebook" in system:
            return {
                "ops": [
                    {
                        "op": "add",
                        "statement": "uint8 overflow wraps on EVM but not on solang",
                        "next_probe": "probe uint64 overflow with 2**63 + 1",
                        "evidence": {
                            "probe": "canned-add",
                            "verdict": "DIVERGENCE",
                            "note": "44 vs 300",
                        },
                    }
                ],
                "reasoning": "overflow semantics differ",
            }
        if "minimize" in system:
            return {"solidity": CANNED_SOURCE}  # refuses to shrink
        raise AssertionError(f"unexpected prompt: {system[:60]}")


class FakeExecutor:
    """Scripted oracle: divergence iff the canned function is still called."""

    def __init__(self):
        self.runs = 0

    def run(self, spec_dict):
        self.runs += 1
        if any(s.get("function") == "add" for s in spec_dict.get("steps", [])):
            return json.loads(json.dumps(DIVERGENT_REPORT))
        return dict(PASS_REPORT)

    def close(self):
        pass


def make_loop(tmp_path, *, budget=100):
    cfg = AgentConfig(
        findings_dir=tmp_path, llm_calls_budget=budget, oracle_runs_budget=50
    )
    llm = FakeLLM(budget)
    loop = HuntLoop(
        cfg,
        client=llm,
        executor=FakeExecutor(),
        store=FindingStore(tmp_path),
        rng_seed=0,
        log=lambda *_: None,
    )
    return loop, llm


def test_loop_records_bug_candidate_finding(tmp_path):
    loop, _ = make_loop(tmp_path)
    summary = loop.hunt(max_rounds=1, only_seeds=["int-semantics"])
    assert summary["rounds"] == 1
    assert summary["new_findings"] == 1
    findings = loop.store.findings()
    assert findings[0]["kinds"] == ["RETURN_MISMATCH"]
    assert findings[0]["triage"]["blame"] == "solang"
    # probe recorded for the memory digest
    assert loop.store.recent_probes(1)[0]["category"] == "bug_candidate"
    # seed coverage tracked
    assert loop.store.seed_stats()["int-semantics"]["probes"] == 1
    # reflect ran and produced an open hypothesis
    assert summary["hypotheses"]["open"] == 1


def test_hypothesis_feeds_next_generation_prompt(tmp_path):
    """The regression test for non-myopia: round 2 must see round 1's hypothesis."""
    loop, llm = make_loop(tmp_path)
    loop.hunt(max_rounds=2, only_seeds=["int-semantics"])
    gen_prompts = [u for s, u in llm.prompts if "differential-testing probes" in s]
    assert len(gen_prompts) == 2
    assert "no hypotheses yet" in gen_prompts[0]
    assert "probe uint64 overflow with 2**63 + 1" in gen_prompts[1]
    assert "[open] h1" in gen_prompts[1]


def test_loop_dedups_repeated_findings(tmp_path):
    loop, _ = make_loop(tmp_path)
    summary = loop.hunt(max_rounds=3, only_seeds=["int-semantics"])
    assert summary["rounds"] == 3
    assert summary["new_findings"] == 1  # same canned probe each round -> dedup
    assert len(loop.store.findings()) == 1


def test_loop_stops_on_llm_budget(tmp_path):
    loop, _ = make_loop(tmp_path, budget=1)
    summary = loop.hunt(max_rounds=10, only_seeds=["int-semantics"])
    assert summary["llm_calls"] <= 1
    assert "budget" in summary["stop_reason"]
