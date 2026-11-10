"""Aggregate human-reviewed bugs and their cost to first witness.

Reviews are append-only JSONL files at ``review/decisions.jsonl`` inside each
run directory.  A decision has the following flexible schema (all fields except
``bug_id`` and ``status`` are optional)::

    {
        "bug_id": "storage-layout",
        "probe_ids": ["probe-id"],
        "finding_ids": ["finding-id"],
        "status": "confirmed_solang_bug",
        "upstream_status": "reported_upstream:123",
        "upstream_url": "https://example.invalid/issues/123",
        "reviewer": "alice",
        "ts": 1730000000.0,
        "rationale": "solc and solang disagree"
    }

Only ``confirmed_solang_bug`` is a confirmed status.  Decisions are applied in
file order (and in caller-supplied run order across runs), never timestamp
order.  Membership is cumulative across all decisions for a bug, while the
last decision determines its status.  Referencing a finding also references
its origin probe, so minimized findings do not replace first-witness cost with
post-minimization cost.

Latest-per-case screening records additionally support audit precision/false-
negative rates and per-bug confirmation effort.  Rates are calculated from
reviewed denominators only; an empty denominator is null, never zero.

The module deliberately uses only the standard library and treats missing
files, legacy records, and unresolved IDs as incomplete evidence rather than
errors.  Such bugs can still be counted, but their first-witness cost fields
remain null.
"""

from __future__ import annotations

import csv
import json
import math
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CONFIRMED_STATUS = "confirmed_solang_bug"
UNSPECIFIED_UPSTREAM_STATUS = "unspecified"


@dataclass
class _Run:
    index: int
    path: Path
    probes: list[dict[str, Any]]
    findings: list[dict[str, Any]]
    screening: list[dict[str, Any]]
    decisions: list[dict[str, Any]]
    probe_by_id: dict[str, dict[str, Any]] = field(init=False)
    probe_order: dict[str, int] = field(init=False)
    finding_by_id: dict[str, dict[str, Any]] = field(init=False)
    screening_by_case: dict[str, dict[str, Any]] = field(init=False)

    def __post_init__(self) -> None:
        self.probe_by_id = {}
        self.probe_order = {}
        for order, probe in enumerate(self.probes):
            # ``id`` is accepted for early experimental probe logs.
            probe_id = _identifier(probe.get("probe_id") or probe.get("id"))
            if probe_id is not None:
                self.probe_by_id[probe_id] = probe
                self.probe_order[probe_id] = order
        self.finding_by_id = {}
        for finding in self.findings:
            finding_id = _identifier(finding.get("id"))
            if finding_id is not None:
                self.finding_by_id[finding_id] = finding
        self.screening_by_case = {}
        for record in self.screening:
            case_id = _identifier(record.get("case_id"))
            if case_id is not None:
                # Screening is append-only too: the last state of a case wins.
                self.screening_by_case[case_id] = record


@dataclass
class _Bug:
    bug_id: str
    status: str | None = None
    upstream_status: str | None = None
    upstream_url: str | None = None
    reviewer: str | None = None
    decision_ts: Any = None
    rationale: str | None = None
    probe_refs: set[tuple[int, str]] = field(default_factory=set)
    finding_refs: set[tuple[int, str]] = field(default_factory=set)
    run_indices: set[int] = field(default_factory=set)

    def apply(self, run_index: int, decision: dict[str, Any]) -> None:
        """Apply one decision; status always advances, metadata is sticky."""
        self.run_indices.add(run_index)
        self.status = _text(decision.get("status"))
        for probe_id in _id_list(decision.get("probe_ids")):
            self.probe_refs.add((run_index, probe_id))
        for finding_id in _id_list(decision.get("finding_ids")):
            self.finding_refs.add((run_index, finding_id))

        # Later status-only decisions should not erase upstream review metadata.
        for field_name, key in (
            ("upstream_status", "upstream_status"),
            ("upstream_url", "upstream_url"),
            ("reviewer", "reviewer"),
            ("rationale", "rationale"),
        ):
            value = _text(decision.get(key))
            if value is not None:
                setattr(self, field_name, value)
        if decision.get("ts") is not None:
            self.decision_ts = decision["ts"]


@dataclass(frozen=True)
class _Witness:
    run_index: int
    probe_id: str
    probe: dict[str, Any]


@dataclass
class _Analysis:
    runs: list[_Run]
    run_rows: list[dict[str, Any]]
    bugs: list[dict[str, Any]]
    discovery: list[dict[str, Any]]
    upstream_status_breakdown: dict[str, int]
    validation: dict[str, Any]

    def summary(self) -> dict[str, Any]:
        return {
            "n_runs": len(self.runs),
            "global_confirmed_bugs": len(self.bugs),
            "runs": self.run_rows,
            "validation": self.validation,
            "upstream_status_breakdown": self.upstream_status_breakdown,
            "bugs": self.bugs,
        }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            record = json.loads(line)
            if not isinstance(record, dict):
                raise ValueError(
                    f"{path}:{line_number}: JSONL record must be an object"
                )
            records.append(record)
    return records


def _identifier(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _text(value: Any) -> str | None:
    return _identifier(value)


def _id_list(value: Any) -> tuple[str, ...]:
    """Accept the schema's arrays and tolerate a legacy singleton string."""
    if isinstance(value, str):
        identifier = _identifier(value)
        return (identifier,) if identifier is not None else ()
    if not isinstance(value, list):
        return ()
    return tuple(
        identifier for item in value if (identifier := _identifier(item)) is not None
    )


def _load_runs(run_dirs: Iterable[str | Path] | str | Path) -> list[_Run]:
    if isinstance(run_dirs, (str, Path)):
        run_dirs = [run_dirs]
    runs: list[_Run] = []
    for index, run_dir in enumerate(run_dirs):
        path = Path(run_dir)
        runs.append(
            _Run(
                index=index,
                path=path,
                probes=_read_jsonl(path / "probes.jsonl"),
                findings=_read_jsonl(path / "findings.jsonl"),
                screening=_read_jsonl(path / "review" / "screening.jsonl"),
                decisions=_read_jsonl(path / "review" / "decisions.jsonl"),
            )
        )
    return runs


def _collect_bugs(runs: list[_Run]) -> dict[str, _Bug]:
    bugs: dict[str, _Bug] = {}
    for run in runs:
        for decision in run.decisions:
            bug_id = _identifier(decision.get("bug_id"))
            if bug_id is None:
                continue
            bug = bugs.setdefault(bug_id, _Bug(bug_id))
            bug.apply(run.index, decision)
    return bugs


def _find_finding(
    runs: list[_Run], run_index: int, finding_id: str
) -> tuple[int, dict[str, Any]] | None:
    """Prefer the deciding run, with a unique cross-run legacy fallback."""
    local = runs[run_index].finding_by_id.get(finding_id)
    if local is not None:
        return run_index, local
    matches = [
        (run.index, finding)
        for run in runs
        if (finding := run.finding_by_id.get(finding_id)) is not None
    ]
    return matches[0] if len(matches) == 1 else None


def _find_probe(runs: list[_Run], run_index: int, probe_id: str) -> _Witness | None:
    """Resolve locally first; fall back only to a globally unique probe ID."""
    local = runs[run_index].probe_by_id.get(probe_id)
    if local is not None:
        return _Witness(run_index, probe_id, local)
    matches = [
        _Witness(run.index, probe_id, probe)
        for run in runs
        if (probe := run.probe_by_id.get(probe_id)) is not None
    ]
    return matches[0] if len(matches) == 1 else None


def _bug_membership(
    bug: _Bug, runs: list[_Run]
) -> tuple[set[tuple[int, str]], set[tuple[int, str]]]:
    """Return direct and finding-origin members, retaining unresolved refs."""
    probe_refs = set(bug.probe_refs)
    finding_refs = set(bug.finding_refs)
    for deciding_run, finding_id in bug.finding_refs:
        located = _find_finding(runs, deciding_run, finding_id)
        if located is None:
            continue
        finding_run, finding = located
        finding_refs.add((finding_run, finding_id))
        origin_probe_id = _identifier(
            finding.get("origin_probe_id") or finding.get("probe_id")
        )
        if origin_probe_id is not None:
            probe_refs.add((finding_run, origin_probe_id))

    # A globally unique ID can repair a legacy cross-run reference.  Local and
    # ambiguous IDs remain scoped to their deciding run.
    for run_index, probe_id in set(probe_refs):
        witness = _find_probe(runs, run_index, probe_id)
        if witness is not None:
            probe_refs.add((witness.run_index, witness.probe_id))
    return probe_refs, finding_refs


def _screening_membership(
    run: _Run, record: dict[str, Any], runs: list[_Run]
) -> tuple[set[tuple[int, str]], set[tuple[int, str]]]:
    """Resolve the probe/finding references carried by one screening case."""
    probe_refs: set[tuple[int, str]] = set()
    finding_refs: set[tuple[int, str]] = set()
    probe_id = _identifier(record.get("probe_id"))
    finding_id = _identifier(record.get("finding_id"))
    if probe_id is not None:
        probe_refs.add((run.index, probe_id))
        witness = _find_probe(runs, run.index, probe_id)
        if witness is not None:
            probe_refs.add((witness.run_index, witness.probe_id))
    if finding_id is not None:
        finding_refs.add((run.index, finding_id))
        located = _find_finding(runs, run.index, finding_id)
        if located is not None:
            finding_run, finding = located
            finding_refs.add((finding_run, finding_id))
            origin_probe_id = _identifier(
                finding.get("origin_probe_id") or finding.get("probe_id")
            )
            if origin_probe_id is not None:
                probe_refs.add((finding_run, origin_probe_id))
    return probe_refs, finding_refs


def _witnesses(
    bug: _Bug,
    runs: list[_Run],
    probe_refs: set[tuple[int, str]] | None = None,
) -> list[_Witness]:
    if probe_refs is None:
        probe_refs, _ = _bug_membership(bug, runs)
    resolved: dict[tuple[int, str], _Witness] = {}
    for run_index, probe_id in probe_refs:
        witness = _find_probe(runs, run_index, probe_id)
        if witness is not None:
            resolved[(witness.run_index, witness.probe_id)] = witness
    return list(resolved.values())


def _sortable_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _additive_number(value: Any) -> int | float:
    """Return a finite numeric contribution; absent/malformed values cost 0."""
    if value is None or isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else 0
    if isinstance(value, str):
        number = _sortable_number(value)
        if number is not None:
            return int(number) if number.is_integer() else number
    return 0


def _confirmation_costs(
    runs: list[_Run],
    probe_refs: set[tuple[int, str]],
    finding_refs: set[tuple[int, str]],
) -> dict[str, int | float]:
    """Sum each latest matching screening case at most once for this bug."""
    totals: dict[str, int | float] = {
        "confirmation_llm_calls": 0,
        "confirmation_llm_tokens": 0,
        "confirmation_oracle_runs": 0,
    }
    for run in runs:
        for screening in run.screening_by_case.values():
            case_probes, case_findings = _screening_membership(run, screening, runs)
            if probe_refs.isdisjoint(case_probes) and finding_refs.isdisjoint(
                case_findings
            ):
                continue
            usage = screening.get("usage")
            usage = usage if isinstance(usage, dict) else {}
            replay = screening.get("replay")
            replay = replay if isinstance(replay, dict) else {}
            totals["confirmation_llm_calls"] += _additive_number(usage.get("calls"))
            totals["confirmation_llm_tokens"] += _additive_number(
                usage.get("total_tokens")
            )
            totals["confirmation_oracle_runs"] += _additive_number(
                replay.get("oracle_runs")
            )
    return totals


def _witness_key(witness: _Witness) -> tuple[Any, ...]:
    ts = _sortable_number(witness.probe.get("ts"))
    oracle_runs = _sortable_number(witness.probe.get("oracle_runs_total"))
    return (
        ts is None,
        ts if ts is not None else 0.0,
        oracle_runs is None,
        oracle_runs if oracle_runs is not None else 0.0,
        witness.run_index,
        witness.probe_id,
    )


def _bug_record(bug: _Bug, runs: list[_Run]) -> dict[str, Any]:
    probe_refs, finding_refs = _bug_membership(bug, runs)
    witnesses = sorted(_witnesses(bug, runs, probe_refs), key=_witness_key)
    first = witnesses[0] if witnesses else None
    probe = first.probe if first is not None else {}
    run_dir = str(runs[first.run_index].path) if first is not None else None

    probe_ids = {probe_id for _, probe_id in probe_refs}
    finding_ids = sorted({finding_id for _, finding_id in finding_refs})
    confirmation_costs = _confirmation_costs(runs, probe_refs, finding_refs)
    return {
        "bug_id": bug.bug_id,
        "status": bug.status,
        "upstream_status": bug.upstream_status,
        "upstream_url": bug.upstream_url,
        "reviewer": bug.reviewer,
        "decision_ts": bug.decision_ts,
        "rationale": bug.rationale,
        "run_dirs": [str(runs[index].path) for index in sorted(bug.run_indices)],
        "probe_ids": sorted(probe_ids),
        "finding_ids": finding_ids,
        "witness_count": len(witnesses),
        "first_witness_run_dir": run_dir,
        "first_witness_probe_id": first.probe_id if first is not None else None,
        "first_witness_ts": probe.get("ts"),
        "oracle_runs_total": probe.get("oracle_runs_total"),
        "llm_calls_total": probe.get("llm_calls_total"),
        "llm_tokens_total": probe.get("llm_tokens_total"),
        **confirmation_costs,
    }


def _record_discovery_key(record: dict[str, Any]) -> tuple[Any, ...]:
    ts = _sortable_number(record.get("first_witness_ts"))
    oracle_runs = _sortable_number(record.get("oracle_runs_total"))
    return (
        ts is None,
        ts if ts is not None else 0.0,
        oracle_runs is None,
        oracle_runs if oracle_runs is not None else 0.0,
        record.get("first_witness_run_dir") or "",
        record.get("first_witness_probe_id") or "",
        record["bug_id"],
    )


def _build_review_index(
    runs: list[_Run], bugs: dict[str, _Bug]
) -> tuple[dict[tuple[int, str], set[str]], dict[tuple[int, str], set[str]]]:
    """Map probe/finding identities to their final, globally clustered bugs."""
    probe_reviews: defaultdict[tuple[int, str], set[str]] = defaultdict(set)
    finding_reviews: defaultdict[tuple[int, str], set[str]] = defaultdict(set)
    for bug_id, bug in bugs.items():
        probe_refs, finding_refs = _bug_membership(bug, runs)
        for ref in probe_refs:
            probe_reviews[ref].add(bug_id)
        for ref in finding_refs:
            finding_reviews[ref].add(bug_id)
    return probe_reviews, finding_reviews


def _case_bug_ids(
    run: _Run,
    screening: dict[str, Any],
    runs: list[_Run],
    probe_reviews: dict[tuple[int, str], set[str]],
    finding_reviews: dict[tuple[int, str], set[str]],
) -> set[str]:
    probe_refs, finding_refs = _screening_membership(run, screening, runs)
    bug_ids: set[str] = set()
    for ref in probe_refs:
        bug_ids.update(probe_reviews.get(ref, set()))
    for ref in finding_refs:
        bug_ids.update(finding_reviews.get(ref, set()))
    return bug_ids


def _has_confirmed_bug(bug_ids: set[str], bugs: dict[str, _Bug]) -> bool:
    return any(bugs[bug_id].status == CONFIRMED_STATUS for bug_id in bug_ids)


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _run_validation(
    run: _Run,
    runs: list[_Run],
    bugs: dict[str, _Bug],
    probe_reviews: dict[tuple[int, str], set[str]],
    finding_reviews: dict[tuple[int, str], set[str]],
) -> dict[str, Any]:
    # Audit all screened online-rejected probes, including offline survivors.
    # Multiple case IDs for one probe are one audit unit, with outcomes unioned.
    rejected_audits: dict[tuple[str, str], set[str]] = {}
    survivor_count = survivor_reviewed = survivor_confirmed = 0
    for case_id, screening in run.screening_by_case.items():
        bug_ids = _case_bug_ids(run, screening, runs, probe_reviews, finding_reviews)
        if _text(screening.get("origin")) == "rejected_probe":
            probe_id = _identifier(screening.get("probe_id"))
            # A missing probe ID still represents a screened case; case_id is
            # the available population identity even when only a finding links.
            key = ("probe", probe_id) if probe_id is not None else ("case", case_id)
            rejected_audits.setdefault(key, set()).update(bug_ids)

        survives = screening.get("survives")
        is_survivor = (
            survives
            if isinstance(survives, bool)
            else _text(screening.get("status")) == "survivor"
        )
        if is_survivor:
            survivor_count += 1
            survivor_reviewed += bool(bug_ids)
            survivor_confirmed += _has_confirmed_bug(bug_ids, bugs)

    rejected_reviewed = sum(bool(ids) for ids in rejected_audits.values())
    rejected_confirmed = sum(
        _has_confirmed_bug(ids, bugs) for ids in rejected_audits.values()
    )

    candidate_seen: set[tuple[str, Any]] = set()
    candidate_count = candidate_reviewed = candidate_confirmed = 0
    for order, probe in enumerate(run.probes):
        if _text(probe.get("category")) != "bug_candidate":
            continue
        probe_id = _identifier(probe.get("probe_id") or probe.get("id"))
        key = ("probe", probe_id) if probe_id is not None else ("record", order)
        if key in candidate_seen:
            continue
        candidate_seen.add(key)
        candidate_count += 1
        bug_ids = (
            set(probe_reviews.get((run.index, probe_id), set()))
            if probe_id is not None
            else set()
        )
        candidate_reviewed += bool(bug_ids)
        candidate_confirmed += _has_confirmed_bug(bug_ids, bugs)

    return {
        "rejected_audit": {
            "screened": len(rejected_audits),
            "reviewed": rejected_reviewed,
            "confirmed": rejected_confirmed,
            "false_negative_rate": _rate(rejected_confirmed, rejected_reviewed),
        },
        "screening": {
            "survivors": survivor_count,
            "reviewed": survivor_reviewed,
            "confirmed": survivor_confirmed,
            "precision": _rate(survivor_confirmed, survivor_reviewed),
        },
        "online_triage": {
            "bug_candidates": candidate_count,
            "reviewed": candidate_reviewed,
            "confirmed": candidate_confirmed,
            "precision": _rate(candidate_confirmed, candidate_reviewed),
        },
    }


def _aggregate_validation(validations: list[dict[str, Any]]) -> dict[str, Any]:
    """Sum audit units across runs, then recompute rates from global totals."""
    rejected_screened = sum(v["rejected_audit"]["screened"] for v in validations)
    rejected_reviewed = sum(v["rejected_audit"]["reviewed"] for v in validations)
    rejected_confirmed = sum(v["rejected_audit"]["confirmed"] for v in validations)
    survivors = sum(v["screening"]["survivors"] for v in validations)
    survivor_reviewed = sum(v["screening"]["reviewed"] for v in validations)
    survivor_confirmed = sum(v["screening"]["confirmed"] for v in validations)
    candidates = sum(v["online_triage"]["bug_candidates"] for v in validations)
    candidate_reviewed = sum(v["online_triage"]["reviewed"] for v in validations)
    candidate_confirmed = sum(v["online_triage"]["confirmed"] for v in validations)
    return {
        "rejected_audit": {
            "screened": rejected_screened,
            "reviewed": rejected_reviewed,
            "confirmed": rejected_confirmed,
            "false_negative_rate": _rate(rejected_confirmed, rejected_reviewed),
        },
        "screening": {
            "survivors": survivors,
            "reviewed": survivor_reviewed,
            "confirmed": survivor_confirmed,
            "precision": _rate(survivor_confirmed, survivor_reviewed),
        },
        "online_triage": {
            "bug_candidates": candidates,
            "reviewed": candidate_reviewed,
            "confirmed": candidate_confirmed,
            "precision": _rate(candidate_confirmed, candidate_reviewed),
        },
    }


def _analyze(run_dirs: Iterable[str | Path] | str | Path) -> _Analysis:
    runs = _load_runs(run_dirs)
    bugs = _collect_bugs(runs)
    confirmed = [bug for bug in bugs.values() if bug.status == CONFIRMED_STATUS]
    records = [_bug_record(bug, runs) for bug in confirmed]
    records.sort(key=lambda record: record["bug_id"])
    probe_reviews, finding_reviews = _build_review_index(runs, bugs)

    run_rows: list[dict[str, Any]] = []
    for run in runs:
        bug_ids = sorted(
            bug.bug_id for bug in confirmed if run.index in bug.run_indices
        )
        validation = _run_validation(run, runs, bugs, probe_reviews, finding_reviews)
        run_rows.append(
            {
                "run_dir": str(run.path),
                "run": run.path.name,
                "confirmed_bugs": len(bug_ids),
                "bug_ids": bug_ids,
                "validation": validation,
            }
        )

    ordered_records = sorted(records, key=_record_discovery_key)
    discovery = [
        {**record, "cumulative_confirmed_bugs": index}
        for index, record in enumerate(ordered_records, start=1)
    ]
    upstream = Counter(
        record["upstream_status"] or UNSPECIFIED_UPSTREAM_STATUS for record in records
    )
    return _Analysis(
        runs=runs,
        run_rows=run_rows,
        bugs=records,
        discovery=discovery,
        upstream_status_breakdown=dict(sorted(upstream.items())),
        validation=_aggregate_validation([row["validation"] for row in run_rows]),
    )


def analyze_run(run_dir: str | Path) -> dict[str, Any]:
    """Return confirmed review metrics for one run without writing files."""
    analysis = _analyze([run_dir])
    run_row = analysis.run_rows[0]
    return {
        **run_row,
        "upstream_status_breakdown": analysis.upstream_status_breakdown,
        "bugs": analysis.bugs,
        "discovery": analysis.discovery,
    }


def _json_cell(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _write_csv(
    path: Path, fieldnames: list[str], rows: Iterable[dict[str, Any]]
) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: _json_cell(value) if isinstance(value, (list, dict)) else value
                    for key, value in row.items()
                    if key in fieldnames
                }
            )


def _markdown_cell(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _write_bug_table(path: Path, bugs: list[dict[str, Any]]) -> None:
    headers = [
        "Bug ID",
        "Runs",
        "First witness",
        "Oracle runs",
        "LLM calls",
        "LLM tokens",
        "Confirmation LLM calls",
        "Confirmation LLM tokens",
        "Confirmation oracle runs",
        "Upstream status",
        "Upstream URL",
        "Reviewer",
        "Rationale",
    ]
    lines = [
        "# Confirmed Solang bugs",
        "",
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for bug in bugs:
        witness = bug["first_witness_probe_id"] or "unresolved"
        values = [
            bug["bug_id"],
            ", ".join(bug["run_dirs"]),
            witness,
            bug["oracle_runs_total"],
            bug["llm_calls_total"],
            bug["llm_tokens_total"],
            bug["confirmation_llm_calls"],
            bug["confirmation_llm_tokens"],
            bug["confirmation_oracle_runs"],
            bug["upstream_status"] or UNSPECIFIED_UPSTREAM_STATUS,
            bug["upstream_url"],
            bug["reviewer"],
            bug["rationale"],
        ]
        lines.append("| " + " | ".join(_markdown_cell(v) for v in values) + " |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def analyze_runs(
    run_dirs: Iterable[str | Path] | str | Path,
    out_dir: str | Path,
) -> dict[str, Any]:
    """Analyze run directories and write confirmed-bug reports to ``out_dir``.

    The same ``bug_id`` is merged globally, while each run row counts that bug
    at most once.  The discovery curve has one point per distinct global bug,
    located at its first witness; additional witnesses never increment it.
    """
    analysis = _analyze(run_dirs)
    summary = analysis.summary()
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    (out_path / "confirmed_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    _write_csv(
        out_path / "confirmed_runs.csv",
        ["run_dir", "run", "confirmed_bugs", "bug_ids"],
        analysis.run_rows,
    )
    _write_csv(
        out_path / "confirmed_discovery.csv",
        [
            "bug_id",
            "first_witness_run_dir",
            "first_witness_probe_id",
            "first_witness_ts",
            "oracle_runs_total",
            "llm_calls_total",
            "llm_tokens_total",
            "cumulative_confirmed_bugs",
        ],
        analysis.discovery,
    )
    _write_csv(
        out_path / "bug_costs.csv",
        [
            "bug_id",
            "status",
            "first_witness_run_dir",
            "first_witness_probe_id",
            "first_witness_ts",
            "oracle_runs_total",
            "llm_calls_total",
            "llm_tokens_total",
            "confirmation_llm_calls",
            "confirmation_llm_tokens",
            "confirmation_oracle_runs",
            "witness_count",
            "run_dirs",
            "probe_ids",
            "finding_ids",
            "upstream_status",
            "upstream_url",
            "reviewer",
            "decision_ts",
            "rationale",
        ],
        analysis.bugs,
    )
    _write_bug_table(out_path / "bug_table.md", analysis.bugs)
    return summary
