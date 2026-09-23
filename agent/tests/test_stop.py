"""Stop-policy tests: budget stops fire at exact counters, saturation stop
fires after K signal-free rounds and stays quiet while signal keeps coming."""

import json
from collections import deque

from agent.config import AgentConfig
from agent.llm import LLMError
from agent.loop import HuntLoop
from agent.stop import LoopState, StopPolicy
from agent.store import FindingStore
from agent.usage import NoUsage

CANNED_SPEC = {
    "name": "canned-quiet",
    "solidity": "// SPDX-License-Identifier: MIT\npragma solidity >=0.8.0;\ncontract c {\n    function f(uint a) public pure returns (uint) { return a; }\n}\n",
    "contract": "c",
    "steps": [{"action": "query", "function": "f", "args": [1]}],
}

PASS_REPORT = {"name": "canned-quiet", "verdict": "PASS", "divergences": []}


class QuietLLM(NoUsage):
    """Every probe PASSes; reflect optionally adds a hypothesis each round."""

    def __init__(self, budget=1000, reflect_ops=None):
        self.calls = 0
        self.budget = budget
        self.reflect_ops = reflect_ops or []

    def budget_left(self):
        return self.budget - self.calls

    def chat_json(
        self, system, user, *, validate=None, max_attempts=3, stage="unknown"
    ):
        if self.budget_left() <= 0:
            raise LLMError("LLM call budget exhausted")
        self.calls += 1
        if "differential-testing probes" in system:
            return dict(CANNED_SPEC)
        if "hypothesis notebook" in system:
            return {"ops": list(self.reflect_ops), "reasoning": "bookkeeping"}
        raise AssertionError(f"unexpected prompt: {system[:60]}")


class QuietExecutor:
    def __init__(self):
        self.runs = 0

    def run(self, spec_dict):
        self.runs += 1
        return dict(PASS_REPORT)

    def close(self):
        pass


def make_loop(tmp_path, *, llm=None):
    cfg = AgentConfig(findings_dir=tmp_path)
    loop = HuntLoop(
        cfg,
        client=llm or QuietLLM(),
        executor=QuietExecutor(),
        store=FindingStore(tmp_path),
        rng_seed=0,
        log=lambda *_: None,
    )
    return loop


def hunt(loop, policy):
    return loop.hunt(policy, only_seeds=["int-semantics"])


def test_stop_reason_keys_are_stable():
    assert set(StopPolicy().check(LoopState()) for _ in range(1)) == {None}
    assert StopPolicy(max_rounds=0).check(LoopState()) == "round_limit"
    assert (
        StopPolicy(oracle_runs_budget=3).check(LoopState(oracle_runs=3))
        == "oracle_budget"
    )
    assert StopPolicy(llm_calls_budget=5).check(LoopState(llm_calls=5)) == "llm_budget"
    state = LoopState(signal_history=deque([False, False]))
    assert StopPolicy(saturation_window=2).check(state) == "saturation"
    state = LoopState(signal_history=deque([False, True]))
    assert StopPolicy(saturation_window=2).check(state) is None


def test_round_limit_stop(tmp_path):
    summary = hunt(make_loop(tmp_path), StopPolicy(max_rounds=3))
    assert summary["rounds"] == 3
    assert summary["stop_reason"] == "round_limit"


def test_oracle_budget_stops_at_exact_counter(tmp_path):
    loop = make_loop(tmp_path)
    summary = hunt(loop, StopPolicy(oracle_runs_budget=3))
    assert summary["oracle_runs"] == 3  # one run per quiet round
    assert summary["stop_reason"] == "oracle_budget"


def test_llm_budget_stops_at_exact_counter(tmp_path):
    loop = make_loop(tmp_path, llm=QuietLLM(budget=100))
    # quiet round: generate + reflect = 2 calls -> budget 5 fires after round 3
    summary = hunt(loop, StopPolicy(llm_calls_budget=5))
    assert summary["stop_reason"] == "llm_budget"
    assert summary["llm_calls"] >= 5
    assert summary["rounds"] == 3


def test_saturation_stops_after_k_quiet_rounds(tmp_path):
    summary = hunt(make_loop(tmp_path), StopPolicy(saturation_window=3))
    assert summary["rounds"] == 3
    assert summary["stop_reason"] == "saturation"


def test_saturation_does_not_fire_while_signal_continues(tmp_path):
    add_op = {
        "op": "add",
        "statement": "something differs",
        "next_probe": "probe again",
    }
    llm = QuietLLM(reflect_ops=[add_op])
    summary = hunt(
        make_loop(tmp_path, llm=llm),
        StopPolicy(max_rounds=5, saturation_window=2),
    )
    assert summary["rounds"] == 5
    assert summary["stop_reason"] == "round_limit"


def test_saturation_window_not_full_means_no_stop(tmp_path):
    summary = hunt(make_loop(tmp_path), StopPolicy(max_rounds=2, saturation_window=10))
    assert summary["rounds"] == 2
    assert summary["stop_reason"] == "round_limit"


def test_probe_records_carry_cumulative_counters(tmp_path):
    loop = make_loop(tmp_path)
    hunt(loop, StopPolicy(max_rounds=2))
    probes = loop.store.probes()
    assert len(probes) == 2
    assert [p["oracle_runs_total"] for p in probes] == [1, 2]
    # recorded after generate (PASS skips the triage call), before reflect
    assert [p["llm_calls_total"] for p in probes] == [1, 3]


def test_hunt_summary_reports_new_stop_reason(tmp_path):
    summary = hunt(make_loop(tmp_path), StopPolicy(max_rounds=1))
    assert summary["stop_reason"] == "round_limit"
    assert summary["oracle_runs"] == 1
    assert summary["llm_calls"] == 2


def test_old_probes_jsonl_without_counters_still_readable(tmp_path):
    loop = make_loop(tmp_path)
    probe_file = tmp_path / "probes.jsonl"
    probe_file.write_text(json.dumps({"ts": 0, "seed": "x", "category": "pass"}) + "\n")
    probes = loop.store.probes()
    assert probes[0]["category"] == "pass"
    assert "oracle_runs_total" not in probes[0]
