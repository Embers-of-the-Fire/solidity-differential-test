"""Unit tests for spec loading/validation (incl. the T2.1 execution mode)."""

import json

import pytest

from oracle.spec import load_test_spec

BASE = {
    "name": "t",
    "solidity": "contract c {}",
    "contract": "c",
    "steps": [],
}


def write(tmp_path, raw):
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(raw))
    return load_test_spec(path)


def test_execution_defaults_to_on_chain(tmp_path):
    assert write(tmp_path, BASE).execution == "on-chain"


def test_execution_dry_run_only_accepted(tmp_path):
    spec = write(tmp_path, {**BASE, "execution": "dry-run-only"})
    assert spec.execution == "dry-run-only"


def test_execution_unknown_value_rejected(tmp_path):
    with pytest.raises(ValueError, match="execution"):
        write(tmp_path, {**BASE, "execution": "simulated"})


def test_storage_mode_validation(tmp_path):
    with pytest.raises(ValueError, match="storage"):
        write(tmp_path, {**BASE, "oracle": {"storage": "fuzzy"}})
