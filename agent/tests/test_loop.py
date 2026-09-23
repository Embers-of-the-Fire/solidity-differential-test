"""Integration test of the full hunt loop with a fake LLM and a scripted oracle.

No chain nodes, no network: proves generate -> run -> triage -> minimize ->
dedup plumbing end to end.
"""

import json

from agent.config import AgentConfig
from agent.llm import LLMError
from agent.loop import HuntLoop
from agent.stop import StopPolicy
from agent.store import FindingStore
from agent.usage import NoUsage

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

# Valid LLM mutant: still calls `add` (so the scripted oracle diverges).
MUTANT_SPEC = {
    "name": "canned-add-mut",
    "solidity": CANNED_SOURCE,
    "contract": "broken",
    "steps": [{"action": "query", "function": "add", "args": [1, 2]}],
}

# Invalid LLM mutant: contract name not declared in the source.
INVALID_MUTANT = {
    "name": "canned-add-broken",
    "solidity": CANNED_SOURCE,
    "contract": "nope",
    "steps": [{"action": "query", "function": "add", "args": [1, 2]}],
}


class FakeLLM(NoUsage):
    def __init__(self, budget=100):
        self.calls = 0
        self.budget = budget
        self.prompts: list[tuple[str, str]] = []

    def budget_left(self):
        return self.budget - self.calls

    def chat_json(
        self, system, user, *, validate=None, max_attempts=3, stage="unknown"
    ):
        if self.budget_left() <= 0:
            raise LLMError("LLM call budget exhausted")
        self.calls += 1
        self.prompts.append((system, user))
        if "mutate existing" in system:
            return {
                "mutants": [
                    dict(MUTANT_SPEC),
                    dict(INVALID_MUTANT),
                ]
            }
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

    def _one(self, spec_dict):
        if any(s.get("function") == "add" for s in spec_dict.get("steps", [])):
            report = json.loads(json.dumps(DIVERGENT_REPORT))
            # spec-dependent detail: each spec gets its own finding fingerprint
            report["divergences"][0]["detail"] += f" [{spec_dict.get('name')}]"
            return report
        return dict(PASS_REPORT)

    def run(self, spec_dict):
        self.runs += 1
        return self._one(spec_dict)

    def run_many(self, spec_dicts):
        self.runs += len(spec_dicts)
        return [self._one(s) for s in spec_dicts]

    def close(self):
        pass


def make_loop(tmp_path, *, budget=100, p_mutate=0.0, reflect="always", admission="on"):
    cfg = AgentConfig(
        findings_dir=tmp_path,
        llm_calls_budget=budget,
        oracle_runs_budget=50,
        p_mutate=p_mutate,
        reflect=reflect,
        admission=admission,
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
    summary = loop.hunt(StopPolicy(max_rounds=1), only_seeds=["int-semantics"])
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
    # findings carry the budget counters for the evaluation harness
    assert findings[0]["oracle_runs_total"] >= 1
    assert findings[0]["llm_calls_total"] >= 1


def test_reflect_never_skips_notebook_calls(tmp_path):
    """Ablation knob: reflect='never' turns the feedback notebook off."""
    loop, llm = make_loop(tmp_path, reflect="never")
    summary = loop.hunt(StopPolicy(max_rounds=2), only_seeds=["int-semantics"])
    assert not [s for s, _ in llm.prompts if "hypothesis notebook" in s]
    assert summary["hypotheses"]["open"] == 0


def test_admission_off_admits_everything(tmp_path):
    """Ablation knob: admission='off' bypasses the interestingness rule."""
    loop, _ = make_loop(tmp_path, admission="off")
    loop.hunt(StopPolicy(max_rounds=2), only_seeds=["int-semantics"])
    entries = loop.store.corpus.entries()
    assert entries
    assert all(e["admitted_by"] == "unfiltered" for e in entries)


def test_hypothesis_feeds_next_generation_prompt(tmp_path):
    """The regression test for non-myopia: round 2 must see round 1's hypothesis."""
    loop, llm = make_loop(tmp_path)
    loop.hunt(StopPolicy(max_rounds=2), only_seeds=["int-semantics"])
    gen_prompts = [u for s, u in llm.prompts if "differential-testing probes" in s]
    assert len(gen_prompts) == 2
    assert "no hypotheses yet" in gen_prompts[0]
    assert "probe uint64 overflow with 2**63 + 1" in gen_prompts[1]
    assert "[open] h1" in gen_prompts[1]


def test_loop_dedups_repeated_findings(tmp_path):
    loop, _ = make_loop(tmp_path)
    summary = loop.hunt(StopPolicy(max_rounds=3), only_seeds=["int-semantics"])
    assert summary["rounds"] == 3
    assert summary["new_findings"] == 1  # same canned probe each round -> dedup
    assert len(loop.store.findings()) == 1


def test_loop_stops_on_llm_budget(tmp_path):
    loop, _ = make_loop(tmp_path, budget=1)
    summary = loop.hunt(loop.default_policy(10), only_seeds=["int-semantics"])
    assert summary["llm_calls"] <= 1
    assert summary["stop_reason"] == "llm_budget"


def test_corpus_admission_via_loop(tmp_path):
    """The corpus grows only through the admission rule, with lineage fields."""
    loop, _ = make_loop(tmp_path)
    loop.hunt(StopPolicy(max_rounds=3), only_seeds=["int-semantics"])
    entries = loop.store.corpus.entries()
    # round 1 admits the divergence; later rounds replay the same canned
    # spec -> known finding + already-seen kind combo -> not admitted
    assert len(entries) == 1
    entry = entries[0]
    assert entry["admitted_by"] == "divergence"
    assert entry["origin"] == "generated"
    assert entry["parent_id"] is None
    assert entry["outcome"]["kinds"] == ["RETURN_MISMATCH"]
    # probes carry lineage metadata
    for probe in loop.store.probes():
        assert probe["origin"] == "generated"
        assert probe["parent_id"] is None
    # the persisted finding spec carries the same meta
    assert loop.store.findings()[0]["spec"]["meta"]["origin"] == "generated"


def test_p_mutate_zero_is_generation_only_baseline(tmp_path):
    """p_mutate=0 never consults the corpus for parents (ablation switch)."""
    loop, _ = make_loop(tmp_path, p_mutate=0.0)
    loop.hunt(StopPolicy(max_rounds=2), only_seeds=["int-semantics"])
    # corpus still grows via admission, but no parent is ever selected:
    # every probe is generated from scratch
    assert len(loop.store.corpus.entries()) == 1
    assert all(p["origin"] == "generated" for p in loop.store.probes())


def test_corpus_file_persists_across_stores(tmp_path):
    loop, _ = make_loop(tmp_path)
    loop.hunt(StopPolicy(max_rounds=1), only_seeds=["int-semantics"])
    reloaded = FindingStore(tmp_path)
    assert len(reloaded.corpus.entries()) == 1


def make_mutation_loop(tmp_path, *, budget=200):
    loop, llm = make_loop(tmp_path, budget=budget, p_mutate=1.0)
    # round 1: corpus is empty, so a parent cannot be selected -> generation
    loop.round(only_seeds=["int-semantics"])
    return loop, llm


def test_mutation_round_runs_a_batch(tmp_path):
    loop, llm = make_mutation_loop(tmp_path)
    summary = loop.round(only_seeds=["int-semantics"])
    parent = loop.store.corpus.entries()[0]
    assert summary["parent_id"] == parent["id"]
    assert summary["origin"] == "mutated"
    # batch = programmatic mutants + 1 valid LLM mutant, all executed
    assert summary["mutants"]
    assert {m["origin"] for m in summary["mutants"]} <= {
        "mutated_prog",
        "mutated_llm",
    }
    assert any(m["origin"] == "mutated_llm" for m in summary["mutants"])
    # the batch-mutation prompt was issued exactly once
    mut_prompts = [u for s, u in llm.prompts if "mutate existing" in s]
    assert len(mut_prompts) == 1


def test_mutation_round_records_invalid_mutant_probes(tmp_path):
    loop, _ = make_mutation_loop(tmp_path)
    summary = loop.round(only_seeds=["int-semantics"])
    assert summary["mutants_invalid"] == 1
    invalid = [p for p in loop.store.probes() if p["category"] == "invalid_probe"]
    assert len(invalid) == 1
    assert invalid[0]["verdict"] == "INVALID"  # recorded, not executed
    assert invalid[0]["origin"] == "mutated_llm"


def test_mutation_round_lineage_and_offspring_feedback(tmp_path):
    loop, _ = make_mutation_loop(tmp_path)
    loop.round(only_seeds=["int-semantics"])
    parent = loop.store.corpus.entries()[0]
    mutated = [
        p for p in loop.store.probes() if p["origin"] in ("mutated_prog", "mutated_llm")
    ]
    assert mutated
    assert all(p["parent_id"] == parent["id"] for p in mutated)
    # every mutant (executed or invalid) fed back into the parent's energy
    assert parent["offspring"]["runs"] == len(mutated)
    assert parent["offspring"]["invalid"] >= 1  # the discarded LLM mutant


def test_mutation_round_minimizes_new_bug_candidates(tmp_path):
    loop, _ = make_mutation_loop(tmp_path)
    summary = loop.round(only_seeds=["int-semantics"])
    # all mutants still call `add` -> all diverge; each has a distinct
    # fingerprint (spec-dependent detail), so each is minimized and recorded
    bug_candidates = [m for m in summary["mutants"] if m["category"] == "bug_candidate"]
    assert bug_candidates
    assert summary["finding_id"] is not None
    assert len(summary["finding_ids"]) == len(bug_candidates)
    assert len(loop.store.findings()) == 1 + len(bug_candidates)  # + round 1
