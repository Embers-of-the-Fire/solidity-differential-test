"""Slow tests for the T2.1 dry-run-only execution mode (RQ4 baseline).

A crafted event-emitting spec diverges in on-chain mode (committed-tx event
comparison) and loses that divergence in dry-run-only mode, where call steps
never commit and event/storage comparison is skipped (tx is None follows the
query path). Requires the devshell binaries.
"""

import json

import pytest

from oracle.runner import DifferentialRunner
from oracle.spec import load_test_spec

# Minimal form of findings/20260923 a1317f13 (solang emits event args with
# stale/final values): a loop emitting the loop variable diverges on-chain.
EVENT_SPEC = {
    "name": "dryrun-contrast",
    "solidity": (
        "pragma solidity >=0.8.0;\n"
        "contract ep {\n"
        "    event S(uint256 x);\n"
        "    function emitMany(uint256 n) external {\n"
        "        for (uint256 i = 0; i < n; i++) { emit S(i); }\n"
        "    }\n"
        "}\n"
    ),
    "contract": "ep",
    "steps": [{"action": "call", "function": "emitMany", "args": [3]}],
}


def run(tmp_path, execution, workdir_name):
    spec_path = tmp_path / f"spec-{workdir_name}.json"
    spec_path.write_text(json.dumps({**EVENT_SPEC, "execution": execution}))
    spec = load_test_spec(spec_path)
    return DifferentialRunner(spec, workdir=tmp_path / workdir_name).run()


@pytest.mark.slow
def test_on_chain_mode_diverges(tmp_path):
    report = run(tmp_path, "on-chain", "onchain")
    assert report["execution"] == "on-chain"
    assert report["verdict"] == "DIVERGENCE", report.get("error")
    assert any(d["kind"] == "EVENT_MISMATCH" for d in report["divergences"])


@pytest.mark.slow
def test_dry_run_only_loses_the_divergence(tmp_path):
    report = run(tmp_path, "dry-run-only", "dryrun")
    assert report["execution"] == "dry-run-only"
    # deployment is still real; call steps never commit
    assert report["deploy"]["evm"]["status"] == "success"
    step = report["steps"][0]
    assert "tx" not in step["evm"] and "tx" not in step["polkadot"]
    assert "state" not in step["evm"] and "state" not in step["polkadot"]
    assert report["verdict"] == "PASS", report["divergences"]
