"""Unit tests for deterministic, LLM-free template spec generation."""

import copy
import json
import random

import pytest

from agent.generator import validate_spec_dict
from agent.seeds import Seed, load_seeds
from agent.template_generator import SUPPORTED_SEED_IDS, generate_template_spec


def _seed(seed_id: str) -> Seed:
    return Seed(id=seed_id, title=seed_id, why="template test")


def _assert_schema_shape(spec: dict) -> None:
    assert isinstance(spec["name"], str) and spec["name"]
    assert isinstance(spec["solidity"], str) and spec["solidity"]
    assert "source_file" not in spec
    assert f"contract {spec['contract']}" in spec["solidity"]
    assert isinstance(spec["constructor"], dict)
    assert isinstance(spec["constructor"].get("args", []), list)
    assert spec["execution"] == "on-chain"
    assert spec["oracle"]["storage"] == "count"
    assert spec["oracle"]["gas"] is False

    steps = spec["steps"]
    assert 1 <= len(steps) <= 8
    assert any(step["action"] == "query" for step in steps)
    for step in steps:
        assert step["action"] in ("call", "query")
        assert isinstance(step["function"], str) and step["function"]
        assert isinstance(step["args"], list)
        assert step["sender"] in ("deployer", "alice", "bob", "charlie")
        assert isinstance(step["value"], int) and 0 <= step["value"] <= 10**15
    json.dumps(spec)


@pytest.mark.parametrize("seed_id", SUPPORTED_SEED_IDS)
def test_all_seed_ids_generate_valid_specs(seed_id: str) -> None:
    for draw in range(8):
        spec = generate_template_spec(_seed(seed_id), random.Random(draw))
        assert validate_spec_dict(spec) == []
        _assert_schema_shape(spec)


def test_packaged_seed_cards_cover_exactly_the_supported_templates() -> None:
    seeds = load_seeds()
    assert {seed.id.replace("-", "_") for seed in seeds} == set(SUPPORTED_SEED_IDS)
    for seed in seeds:
        spec = generate_template_spec(seed, random.Random(19))
        assert validate_spec_dict(spec) == []
        _assert_schema_shape(spec)


@pytest.mark.parametrize("seed_id", SUPPORTED_SEED_IDS)
def test_same_rng_seed_is_deterministic(seed_id: str) -> None:
    first = generate_template_spec(_seed(seed_id), random.Random(12345))
    second = generate_template_spec(_seed(seed_id), random.Random(12345))
    assert first == second
    assert first is not second
    assert first["steps"] is not second["steps"]


@pytest.mark.parametrize("seed_id", SUPPORTED_SEED_IDS)
def test_rng_produces_distinct_specs(seed_id: str) -> None:
    outputs = {
        json.dumps(
            generate_template_spec(_seed(seed_id), random.Random(draw)),
            sort_keys=True,
        )
        for draw in range(12)
    }
    assert len(outputs) > 1


def test_history_arguments_do_not_break_determinism_or_get_mutated() -> None:
    recent = [{"name": "old", "seed": "events", "kinds": ["PASS"]}]
    notebook = {"hypotheses": [{"text": "keep this unchanged"}]}
    recent_snapshot = copy.deepcopy(recent)
    notebook_snapshot = copy.deepcopy(notebook)

    first = generate_template_spec(_seed("events"), random.Random(77), recent, notebook)
    second = generate_template_spec(
        _seed("events"), random.Random(77), recent, notebook
    )

    assert first == second
    assert recent == recent_snapshot
    assert notebook == notebook_snapshot


def test_seed_id_and_dict_forms_are_accepted() -> None:
    from_object = generate_template_spec(_seed("control_flow"), random.Random(4))
    from_dict = generate_template_spec({"id": "control-flow"}, random.Random(4))
    from_string = generate_template_spec("control_flow", random.Random(4))
    assert from_object == from_dict == from_string


def test_unknown_seed_is_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported template seed"):
        generate_template_spec("not_a_seed", random.Random(0))
