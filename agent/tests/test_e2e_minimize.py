"""Slow integration test for the verified reduction pipeline (T1.6).

Runs the full L1 pipeline (no LLM: reduce_llm_rounds=0) on a known divergent
fixture — the gasleft RETURN_MISMATCH, same witness class as the e2e smoke
test — against real chains, and checks the witness record:
verified_one_minimal is true and per-stage run counts sum to the total.

Requires the devshell binaries (solc, solang, anvil, substrate-contracts-node).
"""

import pytest

from agent.executor import Executor, earliest_signature
from agent.minimize import ReduceConfig, minimize

GASLEFT_SPEC = {
    "name": "e2e-minimize-gasleft",
    "solidity": (
        "// SPDX-License-Identifier: MIT\n"
        "pragma solidity >=0.8.0;\n"
        "contract g {\n"
        "    uint256 unused; // dead state for the AST stage to remove\n"
        "    function gl() public view returns (uint256) { return gasleft(); }\n"
        "    function dead() public pure returns (uint256) { return 42; }\n"
        "}\n"
    ),
    "contract": "g",
    "steps": [{"action": "query", "function": "gl"}],
}


@pytest.mark.slow
def test_full_pipeline_produces_verified_one_minimal_witness(tmp_path):
    executor = Executor(parallel=1)
    try:
        report = executor.run(dict(GASLEFT_SPEC))
        assert report["verdict"] == "DIVERGENCE", report.get("error")
        target_sig = earliest_signature(report)
        assert target_sig is not None

        config = ReduceConfig(predicate="signature", llm_rounds=0)
        small_spec, minimality = minimize(
            GASLEFT_SPEC, report, executor.run, config=config
        )
        small_report = executor.run(small_spec)
    finally:
        executor.close()

    # the reduced spec is still the same witness
    assert small_report["verdict"] == "DIVERGENCE"
    assert earliest_signature(small_report) == target_sig
    # the pipeline actually reduced: dead code gone
    assert "function dead" not in small_spec["solidity"]
    assert "uint256 unused" not in small_spec["solidity"]
    # witness record: 1-minimality verified, per-stage counts sum to total
    assert minimality["verified_one_minimal"] is True
    assert minimality["residual_deletable"] == 0
    assert minimality["oracle_runs"] == sum(minimality["stages"].values())
    assert minimality["oracle_runs"] > 0
