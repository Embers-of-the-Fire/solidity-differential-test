"""End-to-end smoke test: runs the counter example on both chains.

Requires the flake devshell binaries (solc, solang, anvil,
substrate-contracts-node). Run inside `nix develop`:

    cd oracle && uv run pytest tests/
"""

from pathlib import Path

import pytest

from oracle.runner import DifferentialRunner
from oracle.spec import load_test_spec

EXAMPLE = Path(__file__).parent.parent / "examples" / "counter.json"


@pytest.mark.slow
def test_counter_example_passes(tmp_path):
    spec = load_test_spec(EXAMPLE)
    report = DifferentialRunner(spec, workdir=tmp_path).run()
    assert report["compile"]["solc"]["ok"], report["compile"]["solc"].get("errors")
    assert report["compile"]["solang"]["ok"], report["compile"]["solang"].get("errors")
    assert report["deploy"]["evm"]["status"] == "success"
    assert report["deploy"]["polkadot"]["status"] == "success"
    assert len(report["steps"]) == len(spec.steps)
    assert report["verdict"] == "PASS", report["divergences"]
