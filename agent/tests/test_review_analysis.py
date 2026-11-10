"""Synthetic JSONL tests for confirmed human-review analysis."""

import csv
import json

from agent.review_analysis import analyze_run, analyze_runs


def write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(record) + "\n" for record in records))


def probe(probe_id, ts, oracle_runs, llm_calls=None, llm_tokens=None):
    return {
        "probe_id": probe_id,
        "ts": ts,
        "oracle_runs_total": oracle_runs,
        "llm_calls_total": llm_calls,
        "llm_tokens_total": llm_tokens,
    }


def read_csv(path):
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def test_clustering_finding_origins_and_earliest_cost(tmp_path):
    run = tmp_path / "run"
    write_jsonl(
        run / "probes.jsonl",
        [
            probe("late", 30, 30, 300, 3000),
            probe("same-time-costlier", 20, 25, 250, 2500),
            probe("first", 20, 20, 200, 2000),
        ],
    )
    write_jsonl(
        run / "findings.jsonl",
        [
            {
                "id": "finding-costlier",
                "ts": 31,
                "origin_probe_id": "same-time-costlier",
                "oracle_runs_total": 999,
                "llm_calls_total": 999,
            },
            {
                "id": "finding-first",
                "ts": 32,
                "origin_probe_id": "first",
                "oracle_runs_total": 999,
                "llm_calls_total": 999,
            },
        ],
    )
    write_jsonl(
        run / "review" / "decisions.jsonl",
        [
            {
                "bug_id": "bug-a",
                "probe_ids": ["late"],
                "finding_ids": ["finding-costlier"],
                "status": "confirmed_solang_bug",
            },
            {
                "bug_id": "bug-a",
                "finding_ids": ["finding-first", "finding-first"],
                "probe_ids": ["first"],
                "status": "confirmed_solang_bug",
            },
        ],
    )

    result = analyze_run(run)
    assert result["confirmed_bugs"] == 1
    bug = result["bugs"][0]
    assert bug["witness_count"] == 3
    assert bug["first_witness_probe_id"] == "first"
    assert bug["oracle_runs_total"] == 20
    assert bug["llm_calls_total"] == 200
    assert bug["llm_tokens_total"] == 2000
    # The minimized finding's post-minimization counters are not witness cost.
    assert bug["oracle_runs_total"] != 999
    assert len(result["discovery"]) == 1


def test_latest_file_order_status_and_upstream_filtering(tmp_path):
    run = tmp_path / "run"
    decisions = [
        {
            "bug_id": "later-rejected",
            "status": "confirmed_solang_bug",
            "upstream_status": "match_found",
            "ts": 999,
        },
        {
            "bug_id": "later-rejected",
            "status": "not_a_solang_bug",
            "ts": 1,
        },
        {
            "bug_id": "later-confirmed",
            "status": "needs_review",
            "upstream_status": "match_found",
        },
        {
            "bug_id": "later-confirmed",
            "status": "confirmed_solang_bug",
            "upstream_status": "no_match_as_of:2026-11-09",
        },
        {"bug_id": "wrong-status", "status": "match_found"},
        {
            "bug_id": "matched",
            "status": "confirmed_solang_bug",
            "upstream_status": "match_found",
        },
        {
            "bug_id": "reported",
            "status": "confirmed_solang_bug",
            "upstream_status": "reported_upstream:42",
        },
        {
            "bug_id": "acknowledged",
            "status": "confirmed_solang_bug",
            "upstream_status": "acknowledged:42",
        },
        {
            "bug_id": "fixed",
            "status": "confirmed_solang_bug",
            "upstream_status": "fixed:42",
        },
        {"bug_id": "not-triaged", "status": "confirmed_solang_bug"},
    ]
    write_jsonl(run / "review" / "decisions.jsonl", decisions)

    result = analyze_run(run)
    assert result["confirmed_bugs"] == 6
    assert "later-rejected" not in result["bug_ids"]
    assert "wrong-status" not in result["bug_ids"]
    assert result["upstream_status_breakdown"] == {
        "acknowledged:42": 1,
        "fixed:42": 1,
        "match_found": 1,
        "no_match_as_of:2026-11-09": 1,
        "reported_upstream:42": 1,
        "unspecified": 1,
    }


def test_cross_run_merge_deduplicates_witnesses_but_not_run_results(tmp_path):
    run_a = tmp_path / "a"
    run_b = tmp_path / "b"
    write_jsonl(run_a / "probes.jsonl", [probe("a-shared", 50, 50, 500, 5000)])
    write_jsonl(
        run_b / "probes.jsonl",
        [probe("b-shared", 10, 10, 100, 1000), probe("b-only", 20, 20, 200, 2000)],
    )
    write_jsonl(
        run_a / "review" / "decisions.jsonl",
        [
            {
                "bug_id": "shared",
                "probe_ids": ["a-shared", "a-shared"],
                "status": "confirmed_solang_bug",
            }
        ],
    )
    write_jsonl(
        run_b / "review" / "decisions.jsonl",
        [
            {
                "bug_id": "shared",
                "probe_ids": ["b-shared"],
                "status": "confirmed_solang_bug",
            },
            {
                "bug_id": "only-b",
                "probe_ids": ["b-only"],
                "status": "confirmed_solang_bug",
            },
        ],
    )

    result = analyze_runs([run_a, run_b], tmp_path / "out")
    assert result["global_confirmed_bugs"] == 2
    assert [(row["run"], row["confirmed_bugs"]) for row in result["runs"]] == [
        ("a", 1),
        ("b", 2),
    ]
    shared = next(bug for bug in result["bugs"] if bug["bug_id"] == "shared")
    assert shared["witness_count"] == 2
    assert shared["first_witness_probe_id"] == "b-shared"
    assert shared["oracle_runs_total"] == 10
    assert [row["bug_id"] for row in result["bugs"]].count("shared") == 1
    discovery = read_csv(tmp_path / "out" / "confirmed_discovery.csv")
    assert [row["bug_id"] for row in discovery] == ["shared", "only-b"]
    assert [row["cumulative_confirmed_bugs"] for row in discovery] == ["1", "2"]


def test_validation_rates_and_confirmation_costs(tmp_path):
    run = tmp_path / "audited"
    candidates = [
        "online-yes",
        "online-no",
        "online-unreviewed",
        "online-finding",
    ]
    other_probes = [
        "audit-yes",
        "audit-no",
        "audit-unreviewed",
        "survivor-yes",
        "survivor-no",
        "survivor-unreviewed",
        "screen-finding-probe",
    ]
    write_jsonl(
        run / "probes.jsonl",
        [
            *[
                {**probe(pid, i + 1, i + 1), "category": "bug_candidate"}
                for i, pid in enumerate(candidates)
            ],
            # Duplicate probe records do not inflate the online-triage total.
            {**probe("online-yes", 1, 1), "category": "bug_candidate"},
            *[
                {**probe(pid, i + 10, i + 10), "category": "oracle_artifact"}
                for i, pid in enumerate(other_probes)
            ],
        ],
    )
    write_jsonl(
        run / "findings.jsonl",
        [
            {"id": "f-online", "origin_probe_id": "online-finding"},
            {"id": "f-screen", "origin_probe_id": "screen-finding-probe"},
        ],
    )
    write_jsonl(
        run / "review" / "decisions.jsonl",
        [
            {
                "bug_id": "online-yes",
                "probe_ids": ["online-yes", "audit-yes", "survivor-yes"],
                "status": "confirmed_solang_bug",
            },
            {
                "bug_id": "online-no",
                "probe_ids": ["online-no", "audit-no", "survivor-no"],
                "status": "confirmed_solang_bug",
            },
            {
                "bug_id": "online-no",
                "probe_ids": ["online-no", "audit-no", "survivor-no"],
                "status": "not_solang_fault",
            },
            {
                "bug_id": "via-findings",
                "finding_ids": ["f-online", "f-screen"],
                "status": "confirmed_solang_bug",
            },
        ],
    )

    def screened(
        case_id,
        origin,
        probe_id,
        survives,
        *,
        finding_id=None,
        calls=None,
        tokens=None,
        oracle_runs=None,
    ):
        return {
            "case_id": case_id,
            "origin": origin,
            "probe_id": probe_id,
            "finding_id": finding_id,
            "status": "survivor" if survives else "rejected",
            "survives": survives,
            "usage": {"calls": calls, "total_tokens": tokens},
            "replay": {"oracle_runs": oracle_runs},
        }

    write_jsonl(
        run / "review" / "screening.jsonl",
        [
            screened("audit-yes", "rejected_probe", "audit-yes", True, calls=99),
            # Only the latest state and usage for a case are used.
            screened(
                "audit-yes",
                "rejected_probe",
                "audit-yes",
                False,
                calls=1,
                tokens=10,
                oracle_runs=1,
            ),
            screened("audit-no", "rejected_probe", "audit-no", False),
            screened("audit-unreviewed-a", "rejected_probe", "audit-unreviewed", False),
            screened("audit-unreviewed-b", "rejected_probe", "audit-unreviewed", False),
            screened(
                "survivor-yes",
                "rejected_probe",
                "survivor-yes",
                True,
                calls=2,
                tokens=20,
                oracle_runs=2,
            ),
            screened("survivor-no", "rejected_probe", "survivor-no", True),
            screened(
                "survivor-unreviewed", "rejected_probe", "survivor-unreviewed", True
            ),
            # This case matches via both probe and finding but is charged once.
            screened(
                "finding-survivor",
                "finding",
                "screen-finding-probe",
                True,
                finding_id="f-screen",
                calls=3,
                tokens=30,
                oracle_runs=3,
            ),
            screened(
                "finding-rejected",
                "finding",
                "screen-finding-probe",
                False,
                finding_id="f-screen",
                calls=5,
                tokens=50,
                oracle_runs=5,
            ),
            screened(
                "online-finding-case",
                "finding",
                "online-finding",
                False,
                finding_id="f-online",
                calls=4,
                tokens=40,
                oracle_runs=4,
            ),
        ],
    )

    result = analyze_run(run)
    expected_validation = {
        "rejected_audit": {
            "screened": 6,
            "reviewed": 4,
            "confirmed": 2,
            "false_negative_rate": 0.5,
        },
        "screening": {
            "survivors": 4,
            "reviewed": 3,
            "confirmed": 2,
            "precision": 2 / 3,
        },
        "online_triage": {
            "bug_candidates": 4,
            "reviewed": 3,
            "confirmed": 2,
            "precision": 2 / 3,
        },
    }
    assert result["validation"] == expected_validation

    bugs = {bug["bug_id"]: bug for bug in result["bugs"]}
    assert bugs["online-yes"]["confirmation_llm_calls"] == 3
    assert bugs["online-yes"]["confirmation_llm_tokens"] == 30
    assert bugs["online-yes"]["confirmation_oracle_runs"] == 3
    assert bugs["via-findings"]["confirmation_llm_calls"] == 12
    assert bugs["via-findings"]["confirmation_llm_tokens"] == 120
    assert bugs["via-findings"]["confirmation_oracle_runs"] == 12

    out = tmp_path / "validation-out"
    summary = analyze_runs([run, tmp_path / "empty"], out)
    assert summary["validation"] == expected_validation
    assert summary["runs"][0]["validation"] == expected_validation
    assert summary["runs"][1]["validation"]["screening"]["precision"] is None
    costs = {row["bug_id"]: row for row in read_csv(out / "bug_costs.csv")}
    assert costs["online-yes"]["confirmation_llm_calls"] == "3"
    assert costs["via-findings"]["confirmation_llm_tokens"] == "120"
    assert costs["via-findings"]["confirmation_oracle_runs"] == "12"


def test_outputs_and_unresolved_legacy_references(tmp_path):
    run = tmp_path / "legacy"
    # Legacy probe IDs and absent counters remain usable.
    write_jsonl(run / "probes.jsonl", [{"id": "old", "ts": 5}])
    write_jsonl(
        run / "findings.jsonl",
        [{"id": "finding-without-origin", "ts": 6, "oracle_runs_total": 6}],
    )
    write_jsonl(
        run / "review" / "decisions.jsonl",
        [
            {
                "bug_id": "legacy",
                "probe_ids": "old",
                "status": "confirmed_solang_bug",
                "upstream_url": "https://example.invalid/1",
                "reviewer": " reviewer ",
                "rationale": "a | markdown pipe",
            },
            {
                "bug_id": "unresolved",
                "probe_ids": ["missing-probe"],
                "finding_ids": ["finding-without-origin", "missing-finding"],
                "status": "confirmed_solang_bug",
            },
        ],
    )
    out = tmp_path / "nested" / "analysis"
    summary = analyze_runs(run, out)

    expected_files = {
        "confirmed_summary.json",
        "confirmed_runs.csv",
        "confirmed_discovery.csv",
        "bug_costs.csv",
        "bug_table.md",
    }
    assert {path.name for path in out.iterdir()} == expected_files
    on_disk = json.loads((out / "confirmed_summary.json").read_text())
    assert on_disk == summary
    assert summary["n_runs"] == 1
    assert summary["global_confirmed_bugs"] == 2

    costs = {row["bug_id"]: row for row in read_csv(out / "bug_costs.csv")}
    assert costs["legacy"]["first_witness_probe_id"] == "old"
    assert costs["legacy"]["oracle_runs_total"] == ""
    assert costs["legacy"]["llm_calls_total"] == ""
    assert costs["unresolved"]["first_witness_probe_id"] == ""
    assert costs["unresolved"]["oracle_runs_total"] == ""
    assert costs["unresolved"]["witness_count"] == "0"

    run_rows = read_csv(out / "confirmed_runs.csv")
    assert run_rows[0]["confirmed_bugs"] == "2"
    assert json.loads(run_rows[0]["bug_ids"]) == ["legacy", "unresolved"]
    # A missing witness does not create an extra discovery/bug row.
    assert len(read_csv(out / "confirmed_discovery.csv")) == 2
    table = (out / "bug_table.md").read_text()
    assert "https://example.invalid/1" in table
    assert "a \\| markdown pipe" in table


def test_missing_review_and_data_files_produce_empty_outputs(tmp_path):
    out = tmp_path / "out"
    summary = analyze_runs([tmp_path / "missing-run"], out)
    assert summary["global_confirmed_bugs"] == 0
    assert summary["runs"][0]["confirmed_bugs"] == 0
    assert summary["validation"]["rejected_audit"]["false_negative_rate"] is None
    assert summary["validation"]["screening"]["precision"] is None
    assert summary["validation"]["online_triage"]["precision"] is None
    assert read_csv(out / "bug_costs.csv") == []
    assert (out / "bug_table.md").read_text().startswith("# Confirmed Solang bugs")
