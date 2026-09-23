"""Evaluation harness: config-as-data ablation runner and metric extraction.

One JSON file describes configurations x repeats x budgets. The fair common
budget is **oracle runs** (configs consume LLM calls differently); LLM calls
and wall clock are reported alongside. Each (config, repeat) gets a fresh
findings dir and a deterministic rng_seed, so runs are resumable-by-rerun
rather than checkpointed. A crashed run is recorded as failed in run.json,
never silently dropped.

Extraction turns the raw JSONL stores (probes/findings/corpus/llm_usage)
into per-run time series and cross-run median + min/max aggregates — no
distributional claims at n=5. Output: summary.json plus one CSV per metric.
"""

from __future__ import annotations

import csv
import dataclasses
import hashlib
import json
import statistics
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import AgentConfig
from .executor import OracleRunner
from .llm import ChatClient
from .loop import HuntLoop
from .stop import StopPolicy
from .usage import summarize_jsonl


class EvalConfigError(Exception):
    """Raised when an ablation matrix file is malformed."""


@dataclass
class EvalBudget:
    oracle_runs: int = 300
    llm_calls: int = 200
    saturation_window: int = 10


@dataclass
class EvalConfigEntry:
    name: str
    overrides: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvalMatrix:
    budget: EvalBudget
    repeats: int
    configs: list[EvalConfigEntry]


_CONFIG_FIELDS = {f.name for f in dataclasses.fields(AgentConfig)}
# findings_dir is owned by the harness (fresh per run); budgets come from the matrix
_RESERVED_OVERRIDES = {
    "findings_dir",
    "oracle_runs_budget",
    "llm_calls_budget",
    "saturation_window",
}


def load_eval_config(path: str | Path) -> EvalMatrix:
    """Load and validate an ablation matrix (configs x repeats x budgets)."""
    try:
        raw = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as e:
        raise EvalConfigError(f"cannot read eval config {path}: {e}") from e
    if not isinstance(raw, dict):
        raise EvalConfigError("eval config must be a JSON object")
    budget_raw = raw.get("budget", {})
    if not isinstance(budget_raw, dict):
        raise EvalConfigError("budget must be an object")
    unknown_budget = set(budget_raw) - {f.name for f in dataclasses.fields(EvalBudget)}
    if unknown_budget:
        raise EvalConfigError(f"unknown budget keys: {sorted(unknown_budget)}")
    budget = EvalBudget(**budget_raw)
    for f in dataclasses.fields(EvalBudget):
        v = getattr(budget, f.name)
        if not isinstance(v, int) or isinstance(v, bool) or v <= 0:
            raise EvalConfigError(f"budget.{f.name} must be a positive int, got {v!r}")
    repeats = raw.get("repeats")
    if not isinstance(repeats, int) or isinstance(repeats, bool) or repeats < 1:
        raise EvalConfigError(f"repeats must be a positive int, got {repeats!r}")
    configs_raw = raw.get("configs")
    if not isinstance(configs_raw, list) or not configs_raw:
        raise EvalConfigError("configs must be a non-empty array")
    configs: list[EvalConfigEntry] = []
    names: set[str] = set()
    for entry in configs_raw:
        if not isinstance(entry, dict):
            raise EvalConfigError("each config must be an object")
        name = entry.get("name")
        overrides = entry.get("overrides", {})
        if not name or not isinstance(name, str):
            raise EvalConfigError("each config needs a non-empty string name")
        if name in names:
            raise EvalConfigError(f"duplicate config name {name!r}")
        names.add(name)
        if not isinstance(overrides, dict):
            raise EvalConfigError(f"{name}: overrides must be an object")
        unknown = set(overrides) - _CONFIG_FIELDS
        if unknown:
            raise EvalConfigError(f"{name}: unknown override keys: {sorted(unknown)}")
        reserved = set(overrides) & _RESERVED_OVERRIDES
        if reserved:
            raise EvalConfigError(f"{name}: reserved override keys: {sorted(reserved)}")
        configs.append(EvalConfigEntry(name=name, overrides=overrides))
    return EvalMatrix(budget=budget, repeats=repeats, configs=configs)


def run_seed(config_name: str, repeat: int) -> int:
    """Deterministic per-run seed (not Python's salted hash())."""
    digest = hashlib.sha256(f"{config_name}:{repeat}".encode()).hexdigest()
    return int(digest[:8], 16)


# --- orchestration -----------------------------------------------------------


def run_matrix(
    matrix: EvalMatrix,
    *,
    base_config: AgentConfig,
    out_root: str | Path,
    client_factory: Callable[[AgentConfig], ChatClient] | None = None,
    executor_factory: Callable[[AgentConfig], OracleRunner] | None = None,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Execute every config x repeat sequentially, then aggregate.

    Factories are injectable for tests; None means the HuntLoop defaults
    (real LLMClient / Executor). Returns the aggregate summary dict.
    """
    out_root = Path(out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    for entry in matrix.configs:
        for repeat in range(matrix.repeats):
            _run_one(
                matrix,
                entry,
                repeat,
                base_config,
                out_root / entry.name / str(repeat),
                client_factory=client_factory,
                executor_factory=executor_factory,
                log=log,
            )
    return aggregate(out_root)


def _run_one(
    matrix: EvalMatrix,
    entry: EvalConfigEntry,
    repeat: int,
    base_config: AgentConfig,
    run_dir: Path,
    *,
    client_factory: Callable[[AgentConfig], ChatClient] | None,
    executor_factory: Callable[[AgentConfig], OracleRunner] | None,
    log: Callable[[str], None],
) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    cfg = dataclasses.replace(
        base_config,
        findings_dir=run_dir,
        oracle_runs_budget=matrix.budget.oracle_runs,
        llm_calls_budget=matrix.budget.llm_calls,
        saturation_window=matrix.budget.saturation_window,
        **entry.overrides,
    )
    seed = run_seed(entry.name, repeat)
    policy = StopPolicy(
        oracle_runs_budget=matrix.budget.oracle_runs,
        llm_calls_budget=matrix.budget.llm_calls,
        saturation_window=matrix.budget.saturation_window,
    )
    prefix = f"[eval {entry.name}#{repeat}]"
    log(f"{prefix} start (rng_seed={seed})")
    record: dict[str, Any] = {
        "config": entry.name,
        "repeat": repeat,
        "overrides": entry.overrides,
        "rng_seed": seed,
        "status": "failed",
        "error": None,
        "summary": None,
    }
    loop = HuntLoop(
        cfg,
        client=client_factory(cfg) if client_factory else None,
        executor=executor_factory(cfg) if executor_factory else None,
        rng_seed=seed,
        log=lambda msg: log(f"{prefix} {msg}"),
    )
    t0 = time.perf_counter()
    try:
        record["summary"] = loop.hunt(policy)
        record["status"] = "ok"
    except Exception as e:  # noqa: BLE001 - a crashed run is a datum, recorded not raised
        record["error"] = f"{type(e).__name__}: {e}"
        record["traceback"] = traceback.format_exc()
        log(f"{prefix} FAILED: {e}")
    finally:
        loop.executor.close()
        record["elapsed_ms"] = (time.perf_counter() - t0) * 1000.0
        (run_dir / "run.json").write_text(json.dumps(record, indent=2))
    if record["status"] == "ok":
        s = record["summary"]
        log(
            f"{prefix} done: {s['rounds']} rounds, {s['new_findings']} "
            f"new finding(s) ({s['stop_reason']})"
        )


# --- extraction ---------------------------------------------------------------


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text().strip().splitlines()
        if line.strip()
    ]


def _finding_oracle_runs(finding: dict[str, Any], probes: list[dict[str, Any]]) -> int:
    """Budget point of a finding; legacy findings lack the counter, so fall
    back to the latest probe counter at or before the finding's timestamp."""
    if finding.get("oracle_runs_total") is not None:
        return finding["oracle_runs_total"]
    ts = finding.get("ts") or 0
    candidates = [
        p["oracle_runs_total"]
        for p in probes
        if p.get("oracle_runs_total") is not None and (p.get("ts") or 0) <= ts
    ]
    return max(candidates, default=0)


def extract_run(run_dir: str | Path) -> dict[str, Any]:
    """Per-run metrics + time series from one findings dir.

    Failed/partial runs return status != "ok" with metrics None.
    """
    run_dir = Path(run_dir)
    record: dict[str, Any] = {
        "run_dir": str(run_dir),
        "config": run_dir.parent.name,
        "repeat": run_dir.name,
        "status": "missing_run_json",
    }
    run_json = run_dir / "run.json"
    if run_json.exists():
        try:
            record.update(json.loads(run_json.read_text()))
        except json.JSONDecodeError:
            record["status"] = "corrupt_run_json"
    if record.get("status") != "ok":
        record["metrics"] = None
        return record

    probes = _read_jsonl(run_dir / "probes.jsonl")
    findings = _read_jsonl(run_dir / "findings.jsonl")
    corpus = _read_jsonl(run_dir / "corpus.jsonl")
    usage = summarize_jsonl(run_dir / "llm_usage.jsonl")
    summary = record.get("summary") or {}

    oracle_runs = summary.get("oracle_runs") or max(
        (p.get("oracle_runs_total") or 0 for p in probes), default=0
    )
    llm_calls = summary.get("llm_calls") or usage["totals"]["calls"]
    wall_s = (record.get("elapsed_ms") or summary.get("elapsed_ms") or 0.0) / 1000.0

    timestamps = [ts for x in probes + findings if (ts := x.get("ts")) is not None]
    start_ts = min(timestamps, default=None)
    series = [
        {
            "oracle_runs": _finding_oracle_runs(f, probes),
            "wall_s": (f.get("ts") - start_ts) if start_ts and f.get("ts") else None,
            "findings": i + 1,
        }
        for i, f in enumerate(sorted(findings, key=lambda f: f.get("ts") or 0))
    ]
    series.append(
        {"oracle_runs": oracle_runs, "wall_s": wall_s, "findings": len(findings)}
    )

    origins: dict[str, dict[str, Any]] = {}
    for p in probes:
        o = p.get("origin") or "unknown"
        acc = origins.setdefault(
            o,
            {"probes": 0, "oracle_artifact": 0, "invalid_probe": 0, "bug_candidate": 0},
        )
        acc["probes"] += 1
        if p.get("category") in acc:
            acc[p["category"]] += 1
    admitted_by_origin: dict[str, int] = {}
    for e in corpus:
        o = e.get("origin") or "unknown"
        admitted_by_origin[o] = admitted_by_origin.get(o, 0) + 1
    for o, acc in origins.items():
        acc["admitted"] = admitted_by_origin.get(o, 0)

    llm_probes = origins.get("mutated_llm", {}).get("probes", 0)
    llm_invalid = origins.get("mutated_llm", {}).get("invalid_probe", 0)
    executed = sum(a["probes"] for a in origins.values())
    admitted = sum(a["admitted"] for a in origins.values())
    n_findings = len(findings)
    record["metrics"] = {
        "rounds": summary.get("rounds"),
        "stop_reason": summary.get("stop_reason"),
        "oracle_runs": oracle_runs,
        "llm_calls": llm_calls,
        "wall_s": wall_s,
        "unique_findings": n_findings,
        "findings_per_100_oracle_runs": (
            100.0 * n_findings / oracle_runs if oracle_runs else 0.0
        ),
        "llm_calls_per_finding": (llm_calls / n_findings) if n_findings else None,
        "mutant_discard_rate": (llm_invalid / llm_probes) if llm_probes else None,
        "corpus_admission_rate": (admitted / executed) if executed else None,
        "origins": origins,
        "usage_totals": usage["totals"],
        "series": series,
    }
    return record


# --- aggregation ---------------------------------------------------------------


def _median_min_max(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"median": None, "min": None, "max": None}
    return {
        "median": statistics.median(values),
        "min": min(values),
        "max": max(values),
    }


def _curve_at(series: list[dict[str, Any]], oracle_runs: int) -> int:
    """Step function: cumulative findings at a given oracle-run budget."""
    value = 0
    for pt in series:
        if pt["oracle_runs"] <= oracle_runs:
            value = pt["findings"]
        else:
            break
    return value


def aggregate(out_root: str | Path) -> dict[str, Any]:
    """Aggregate all runs under out_root; write summary.json + CSVs."""
    out_root = Path(out_root)
    runs: list[dict[str, Any]] = []
    if out_root.is_dir():
        for config_dir in sorted(p for p in out_root.iterdir() if p.is_dir()):
            for run_dir in sorted(p for p in config_dir.iterdir() if p.is_dir()):
                runs.append(extract_run(run_dir))

    by_config: dict[str, list[dict[str, Any]]] = {}
    for run in runs:
        by_config.setdefault(str(run.get("config")), []).append(run)

    configs: dict[str, Any] = {}
    for name, group in sorted(by_config.items()):
        ok = [r for r in group if r.get("status") == "ok" and r.get("metrics")]
        failed = [r for r in group if r not in ok]
        metrics = [r["metrics"] for r in ok]
        stop_reasons: dict[str, int] = {}
        for m in metrics:
            reason = m.get("stop_reason") or "unknown"
            stop_reasons[reason] = stop_reasons.get(reason, 0) + 1
        budget_max = max((m["oracle_runs"] for m in metrics), default=0)
        curves = [m["series"] for m in metrics]
        saturation = [
            {
                "oracle_runs": g,
                **_median_min_max([_curve_at(c, g) for c in curves]),
            }
            for g in range(budget_max + 1)
        ]
        configs[name] = {
            "n_ok": len(ok),
            "n_failed": len(failed),
            "stop_reasons": stop_reasons,
            "unique_findings": _median_min_max([m["unique_findings"] for m in metrics]),
            "findings_per_100_oracle_runs": _median_min_max(
                [m["findings_per_100_oracle_runs"] for m in metrics]
            ),
            "llm_calls_per_finding": _median_min_max(
                [
                    m["llm_calls_per_finding"]
                    for m in metrics
                    if m["llm_calls_per_finding"] is not None
                ]
            ),
            "oracle_runs": _median_min_max([m["oracle_runs"] for m in metrics]),
            "wall_s": _median_min_max([m["wall_s"] for m in metrics]),
            "saturation": saturation,
        }

    summary = {
        "generated_at": time.time(),
        "out_root": str(out_root),
        "n_runs": len(runs),
        "configs": configs,
        "runs": runs,
    }
    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / "summary.json").write_text(json.dumps(summary, indent=2))
    _write_runs_csv(out_root / "runs.csv", runs)
    _write_origins_csv(out_root / "origins.csv", runs)
    _write_saturation_csv(out_root / "saturation.csv", configs)
    return summary


def _write_runs_csv(path: Path, runs: list[dict[str, Any]]) -> None:
    fields = [
        "config",
        "repeat",
        "status",
        "stop_reason",
        "rounds",
        "oracle_runs",
        "llm_calls",
        "wall_s",
        "unique_findings",
        "findings_per_100_oracle_runs",
        "llm_calls_per_finding",
        "mutant_discard_rate",
        "corpus_admission_rate",
        "error",
    ]
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for run in runs:
            m = run.get("metrics") or {}
            writer.writerow(
                {
                    "config": run.get("config"),
                    "repeat": run.get("repeat"),
                    "status": run.get("status"),
                    "stop_reason": m.get("stop_reason"),
                    "rounds": m.get("rounds"),
                    "oracle_runs": m.get("oracle_runs"),
                    "llm_calls": m.get("llm_calls"),
                    "wall_s": m.get("wall_s"),
                    "unique_findings": m.get("unique_findings"),
                    "findings_per_100_oracle_runs": m.get(
                        "findings_per_100_oracle_runs"
                    ),
                    "llm_calls_per_finding": m.get("llm_calls_per_finding"),
                    "mutant_discard_rate": m.get("mutant_discard_rate"),
                    "corpus_admission_rate": m.get("corpus_admission_rate"),
                    "error": run.get("error"),
                }
            )


def _write_origins_csv(path: Path, runs: list[dict[str, Any]]) -> None:
    fields = [
        "config",
        "repeat",
        "origin",
        "probes",
        "oracle_artifact",
        "invalid_probe",
        "bug_candidate",
        "admitted",
    ]
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for run in runs:
            m = run.get("metrics")
            if not m:
                continue
            for origin, acc in sorted(m["origins"].items()):
                writer.writerow(
                    {
                        "config": run.get("config"),
                        "repeat": run.get("repeat"),
                        "origin": origin,
                        **{k: acc.get(k, 0) for k in fields[3:]},
                    }
                )


def _write_saturation_csv(path: Path, configs: dict[str, Any]) -> None:
    fields = ["config", "oracle_runs", "median", "min", "max"]
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for name, agg in configs.items():
            for pt in agg["saturation"]:
                writer.writerow({"config": name, **pt})
