"""Timing tracing: the oracle report records elapsed times for every stage.

Uses the same e2e setup as the smoke test (spawns both chain nodes), plus a
pure-Markdown unit check that does not need the devshell binaries.
"""

from pathlib import Path

import pytest

from oracle.report import render_markdown
from oracle.runner import DifferentialRunner
from oracle.spec import load_test_spec
from oracle.timing import Timer, now_iso

EXAMPLE = Path(__file__).parent.parent / "examples" / "counter.json"


def test_timer_measures_positive_elapsed():
    with Timer() as t:
        sum(range(1000))
    assert t.elapsed_ms is not None
    assert t.elapsed_ms >= 0
    assert "T" in now_iso()  # ISO 8601


@pytest.mark.slow
def test_report_carries_timing(tmp_path):
    spec = load_test_spec(EXAMPLE)
    report = DifferentialRunner(spec, workdir=tmp_path).run()
    assert report["verdict"] == "PASS", report["divergences"]

    timing = report["timing"]
    assert timing["started_at"]
    assert timing["started_epoch"] > 0
    assert timing["total_ms"] > 0
    for chain in ("evm", "polkadot"):
        assert timing["nodes"][chain]["start_ms"] > 0
        assert timing["nodes"][chain]["stop_ms"] is not None

    assert report["compile"]["solc"]["elapsed_ms"] > 0
    assert report["compile"]["solang"]["elapsed_ms"] > 0
    assert report["deploy"]["evm"]["elapsed_ms"] > 0
    assert report["deploy"]["polkadot"]["elapsed_ms"] > 0

    for step in report["steps"]:
        st = step["timing"]
        for chain in ("evm", "polkadot"):
            assert st[chain]["dry_run_ms"] is not None
            assert st[f"{chain}_total_ms"] > 0
            if step["action"] == "call":
                assert st[chain]["tx_ms"] is not None
                assert st[chain]["snapshot_ms"] is not None

    md = render_markdown(report)
    assert "## Timing" in md
    assert "Total wall time" in md
