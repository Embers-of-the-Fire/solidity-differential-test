"""Unit and property tests for the mutation operators.

Every mutant must pass `validate_spec_dict` (a failure is an operator bug),
differ from its parent, and only reference declared functions.
"""

import copy
import json
import random

from agent.corpus import spec_id
from agent.generator import _function_declared, validate_spec_dict
from agent.llm import LLMError
from agent.mutate import (
    duplicate_step,
    insert_readback,
    llm_mutants,
    perturb_args,
    programmatic_mutants,
    shuffle_calls,
    swap_sender,
    zero_value,
)
from agent.seeds import Seed
from agent.usage import NoUsage

SOURCE = """// SPDX-License-Identifier: MIT
pragma solidity >=0.8.0;
contract counter {
    uint256 public count;
    bool public flag;

    function add(uint256 x) public { count += x; }
    function flip() public { flag = !flag; }
    function pay() public payable { count += 1; }
}
"""

PARENT = {
    "name": "counter-parent",
    "solidity": SOURCE,
    "contract": "counter",
    "oracle": {"storage": "count", "gas": False},
    "steps": [
        {"action": "call", "function": "add", "args": [255], "sender": "alice"},
        {"action": "call", "function": "flip", "sender": "bob"},
        {"action": "call", "function": "pay", "sender": "alice", "value": 100},
        {"action": "query", "function": "count"},
    ],
}

OPERATORS = [
    shuffle_calls,
    duplicate_step,
    perturb_args,
    swap_sender,
    insert_readback,
    zero_value,
]

SEED = Seed(id="s", title="t", why="w")
NOTEBOOK = {"hypotheses": []}


def assert_valid_distinct(mutant, parent=PARENT):
    assert validate_spec_dict(mutant) == []
    assert spec_id(mutant) != spec_id(parent)
    for step in mutant["steps"]:
        assert _function_declared(step["function"], mutant["solidity"])


def test_each_operator_produces_a_valid_distinct_mutant():
    for op in OPERATORS:
        mutant = op(PARENT, random.Random(0))
        assert_valid_distinct(mutant)


def test_shuffle_calls_swaps_adjacent_calls_keeps_queries():
    mutant = shuffle_calls(PARENT, random.Random(0))
    # the trailing query on `count` never moves before the calls
    assert mutant["steps"][-1] == {"action": "query", "function": "count"}
    assert sorted(s["function"] for s in mutant["steps"]) == sorted(
        s["function"] for s in PARENT["steps"]
    )


def test_perturb_args_changes_one_arg():
    for seed in range(20):
        mutant = perturb_args(PARENT, random.Random(seed))
        before = [s.get("args") for s in PARENT["steps"]]
        after = [s.get("args") for s in mutant["steps"]]
        assert after != before


def test_perturb_args_numeric_boundaries():
    parent = copy.deepcopy(PARENT)
    parent["steps"][0]["args"] = [8]  # bit-width 4 -> boundaries 15, 16, 4
    seen = set()
    for seed in range(200):
        mutant = perturb_args(parent, random.Random(seed))
        seen.add(mutant["steps"][0]["args"][0])
    assert seen - {8}  # actually perturbed
    assert all(isinstance(v, int) for v in seen)


def test_swap_sender_stays_in_allowed_set():
    mutant = swap_sender(PARENT, random.Random(0))
    senders = {s.get("sender", "deployer") for s in mutant["steps"]}
    assert senders <= {"deployer", "alice", "bob", "charlie"}
    assert mutant["steps"] != PARENT["steps"]


def test_insert_readback_queries_a_declared_zero_arg_function():
    mutant = insert_readback(PARENT, random.Random(0))
    assert len(mutant["steps"]) == len(PARENT["steps"]) + 1
    queries = [s for s in mutant["steps"] if s["action"] == "query"]
    assert len(queries) == 2
    assert all("args" not in q for q in queries)  # never invents arguments
    assert {q["function"] for q in queries} <= {"count", "flag", "flip", "pay"}


def test_zero_value_clears_a_nonzero_value():
    mutant = zero_value(PARENT, random.Random(0))
    assert all(s.get("value", 0) == 0 for s in mutant["steps"])


def test_operators_never_mutate_the_parent():
    snapshot = copy.deepcopy(PARENT)
    for op in OPERATORS:
        op(PARENT, random.Random(0))
    assert snapshot == PARENT


def test_property_random_applications_always_valid():
    rng = random.Random(42)
    for _ in range(100):
        m = copy.deepcopy(PARENT)
        for _ in range(rng.randrange(1, 4)):
            m = rng.choice(OPERATORS)(m, rng)
        assert validate_spec_dict(m) == []


def test_programmatic_mutants_dedup_and_validate():
    mutants, failures = programmatic_mutants(
        PARENT, random.Random(0), k=4, ops_per_mutant=2
    )
    assert failures == 0
    assert mutants
    ids = {spec_id(m) for m in mutants}
    assert len(ids) == len(mutants)
    assert spec_id(PARENT) not in ids
    for m in mutants:
        assert "meta" not in m


class FakeMutateLLM(NoUsage):
    """Answers the batch-mutation prompt with a scripted envelope."""

    def __init__(self, mutants):
        self.calls = 0
        self.mutants = mutants
        self.prompts = []

    def budget_left(self):
        return 100 - self.calls

    def chat_json(self, system, user, *, validate=None, max_attempts=3, stage=""):
        self.calls += 1
        self.prompts.append((system, user))
        out = {"mutants": [copy.deepcopy(m) for m in self.mutants]}
        if validate:
            problems = validate(out)
            assert not problems, problems
        return out


VALID_MUTANT = {
    "name": "counter-mut-1",
    "solidity": SOURCE.replace("count += x", "count += x + 1"),
    "contract": "counter",
    "steps": [{"action": "call", "function": "add", "args": [255]}],
}

INVALID_MUTANT = {
    "name": "counter-mut-broken",
    "solidity": SOURCE,
    "contract": "nope",  # not declared in the source
    "steps": [{"action": "call", "function": "add", "args": [1]}],
}


def test_llm_mutants_valid_batch():
    client = FakeMutateLLM([VALID_MUTANT])
    valid, invalid = llm_mutants(
        client, PARENT, "DIVERGENCE/bug_candidate", SEED, NOTEBOOK, 1
    )
    assert invalid == []
    assert len(valid) == 1
    assert valid[0]["oracle"]["gas"] is False
    assert valid[0]["oracle"]["storage"] == "count"


def test_llm_mutants_discards_invalid_without_repair():
    client = FakeMutateLLM([VALID_MUTANT, INVALID_MUTANT])
    valid, invalid = llm_mutants(client, PARENT, "PASS/pass", SEED, NOTEBOOK, 2)
    assert [m["name"] for m in valid] == ["counter-mut-1"]
    assert [m["name"] for m in invalid] == ["counter-mut-broken"]
    assert client.calls == 1  # one batch call, no per-mutant repair


def test_llm_mutants_drops_parent_clones():
    client = FakeMutateLLM([copy.deepcopy(PARENT)])
    valid, invalid = llm_mutants(client, PARENT, "PASS/pass", SEED, NOTEBOOK, 1)
    assert valid == []
    assert invalid == []  # duplicates are not "invalid", just dropped


def test_llm_mutants_prompt_contains_menu_and_parent():
    client = FakeMutateLLM([VALID_MUTANT])
    llm_mutants(client, PARENT, "PASS/pass", SEED, NOTEBOOK, 3)
    _, user = client.prompts[0]
    assert "Mutation menu" in user
    assert json.dumps(PARENT, indent=2) in user
    assert '"mutants": [<spec>' in user or "mutants" in user


def test_llm_mutants_propagates_llm_failure():
    class DownLLM(NoUsage):
        calls = 0

        def budget_left(self):
            return 0

        def chat_json(self, *a, **k):
            raise LLMError("budget exhausted")

    try:
        llm_mutants(DownLLM(), PARENT, "PASS/pass", SEED, NOTEBOOK, 1)
        raise AssertionError("expected LLMError")
    except LLMError:
        pass
