"""Unit tests for the evaluation harness: config validation, orchestration
with fake client/executor, and metric extraction/aggregation.

No chain nodes, no network: the matrix runs through the same FakeLLM /
FakeExecutor plumbing as test_loop.
"""

import json
from pathlib import Path

import pytest
from test_loop import FakeExecutor, FakeLLM

from agent.config import AgentConfig
from agent.evaluate import (
    EvalConfigError,
    aggregate,
    extract_run,
    load_eval_config,
    run_matrix,
    run_seed,
)

TOY_MATRIX = {
    "budget": {"oracle_runs": 3, "llm_calls": 1000, "saturation_window": 50},
    "repeats": 2,
    "configs": [
        {"name": "gen", "overrides": {"p_mutate": 0.0}},
        {"name": "mut", "overrides": {"p_mutate": 1.0}},
    ],
}


def write_matrix(tmp_path, matrix=None):
    path = tmp_path / "matrix.json"
    path.write_text(json.dumps(matrix if matrix is not None else TOY_MATRIX))
    return path


def test_shipped_ablations_matrix_is_valid():
    repo_matrix = Path(__file__).parents[1] / "eval" / "ablations.json"
    matrix = load_eval_config(repo_matrix)
    assert matrix.repeats == 5
    assert [c.name for c in matrix.configs] == [
        "baseline-generation",
        "mutation-prog-only",
        "mutation-llm-only",
        "hybrid",
        "hybrid-no-reflect",
        "hybrid-no-admission",
    ]


def test_load_eval_config_valid(tmp_path):
    matrix = load_eval_config(write_matrix(tmp_path))
    assert matrix.budget.oracle_runs == 3
    assert matrix.repeats == 2
    assert matrix.configs[1].overrides == {"p_mutate": 1.0}


@pytest.mark.parametrize(
    "mutate, match",
    [
        (lambda m: m["configs"][0]["overrides"].update(nope=1), "unknown override"),
        (lambda m: m["configs"][0]["overrides"].update(findings_dir="x"), "reserved"),
        (
            lambda m: m["configs"][0]["overrides"].update(oracle_runs_budget=5),
            "reserved",
        ),
        (lambda m: m["configs"].append(dict(m["configs"][0])), "duplicate"),
        (lambda m: m.update(repeats=0), "repeats"),
        (lambda m: m["budget"].update(oracle_runs=-1), "positive int"),
        (lambda m: m["budget"].update(gpus=4), "unknown budget"),
    ],
)
def test_load_eval_config_rejects_bad_matrices(tmp_path, mutate, match):
    matrix = json.loads(json.dumps(TOY_MATRIX))
    mutate(matrix)
    with pytest.raises(EvalConfigError, match=match):
        load_eval_config(write_matrix(tmp_path, matrix))


def test_run_seed_deterministic_and_distinct():
    assert run_seed("hybrid", 0) == run_seed("hybrid", 0)
    seeds = {run_seed("hybrid", r) for r in range(5)}
    assert len(seeds) == 5
    assert run_seed("a", 0) != run_seed("b", 0)


def run_toy_matrix(tmp_path, executor_factory=None):
    out_root = tmp_path / "eval"
    seen_cfgs = []

    def client_factory(cfg):
        seen_cfgs.append(cfg)
        return FakeLLM(budget=1000)

    summary = run_matrix(
        load_eval_config(write_matrix(tmp_path)),
        base_config=AgentConfig(),
        out_root=out_root,
        client_factory=client_factory,
        executor_factory=executor_factory or (lambda cfg: FakeExecutor()),
        log=lambda *_: None,
    )
    return summary, out_root, seen_cfgs


def test_run_matrix_overrides_dirs_and_seeds(tmp_path):
    summary, out_root, seen_cfgs = run_toy_matrix(tmp_path)
    # one client per config x repeat; overrides and fresh dirs propagated
    assert len(seen_cfgs) == 4
    by_dir = {cfg.findings_dir: cfg for cfg in seen_cfgs}
    assert by_dir[out_root / "gen" / "0"].p_mutate == 0.0
    assert by_dir[out_root / "mut" / "1"].p_mutate == 1.0
    assert all(cfg.oracle_runs_budget == 3 for cfg in seen_cfgs)
    # each run recorded with a deterministic, distinct seed
    records = {}
    for config in ("gen", "mut"):
        for repeat in (0, 1):
            rec = json.loads((out_root / config / str(repeat) / "run.json").read_text())
            assert rec["status"] == "ok"
            assert rec["rng_seed"] == run_seed(config, repeat)
            records[(config, repeat)] = rec
    assert len({r["rng_seed"] for r in records.values()}) == 4
    # aggregation outputs exist and are well-formed
    assert summary["n_runs"] == 4
    for name in ("gen", "mut"):
        agg = summary["configs"][name]
        assert agg["n_ok"] == 2 and agg["n_failed"] == 0
        assert agg["unique_findings"]["median"] >= 1
        assert agg["saturation"]
    for fname in ("summary.json", "runs.csv", "origins.csv", "saturation.csv"):
        assert (out_root / fname).exists()


def test_extract_run_metrics(tmp_path):
    _, out_root, _ = run_toy_matrix(tmp_path)
    run = extract_run(out_root / "gen" / "0")
    assert run["status"] == "ok"
    m = run["metrics"]
    assert m["unique_findings"] >= 1
    assert m["oracle_runs"] >= 1
    assert m["findings_per_100_oracle_runs"] > 0
    assert m["llm_calls_per_finding"] is not None
    # time series is non-decreasing and ends at the run totals
    pts = m["series"]
    assert [p["findings"] for p in pts] == sorted(p["findings"] for p in pts)
    assert pts[-1]["findings"] == m["unique_findings"]
    assert pts[-1]["oracle_runs"] == m["oracle_runs"]
    # per-origin breakdown recorded
    assert m["origins"]["generated"]["probes"] >= 1


class BoomExecutor:
    """Oracle that always crashes: the run must be recorded as failed."""

    def __init__(self):
        self.runs = 0

    def run(self, spec_dict):
        self.runs += 1
        raise RuntimeError("boom")

    def run_many(self, spec_dicts):
        self.runs += len(spec_dicts)
        raise RuntimeError("boom")

    def close(self):
        pass


def test_failed_run_is_recorded_not_dropped(tmp_path):
    summary, out_root, _ = run_toy_matrix(
        tmp_path, executor_factory=lambda cfg: BoomExecutor()
    )
    rec = json.loads((out_root / "gen" / "0" / "run.json").read_text())
    assert rec["status"] == "failed"
    assert "RuntimeError: boom" in rec["error"]
    agg = summary["configs"]["gen"]
    assert agg["n_ok"] == 0
    assert agg["n_failed"] == 2
    # failed runs excluded from metric medians but still visible
    assert agg["unique_findings"]["median"] is None
    extracted = extract_run(out_root / "gen" / "0")
    assert extracted["status"] == "failed"
    assert extracted["metrics"] is None
    # the CSV still lists the failed runs
    rows = (out_root / "runs.csv").read_text().strip().splitlines()
    assert len(rows) == 1 + 4


def test_extract_run_missing_run_json(tmp_path):
    run_dir = tmp_path / "eval" / "ghost" / "0"
    run_dir.mkdir(parents=True)
    run = extract_run(run_dir)
    assert run["status"] == "missing_run_json"
    assert run["metrics"] is None


def test_aggregate_on_empty_root(tmp_path):
    summary = aggregate(tmp_path / "empty")
    assert summary["n_runs"] == 0
    assert summary["configs"] == {}
    assert (tmp_path / "empty" / "summary.json").exists()
