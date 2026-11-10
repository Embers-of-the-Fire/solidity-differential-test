"""Offline, evidence-preserving adjudication of divergent probes and findings.

Screening never mutates findings or feeds back into corpus admission. LLM votes
are review aids; human semantic and upstream decisions live in separate files.
"""

from __future__ import annotations

import json
import random
import re
import time
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any

from .config import AgentConfig
from .executor import earliest_signature, run_spec_dict
from .llm import ChatClient, LLMError
from .minimize import ReduceConfig, minimize
from .prompts import load_prompt

CATEGORIES = {
    "known_semantic",
    "oracle_artifact",
    "bug_candidate",
    "invalid_probe",
    "not_solang_fault",
}


@dataclass
class ReviewCase:
    case_id: str
    spec: dict[str, Any]
    report: dict[str, Any]
    probe_id: str | None = None
    finding_id: str | None = None
    origin: str = "finding"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text().strip().splitlines()
        if line.strip()
    ]


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(record) + "\n")


def _artifact(root: Path, probe: dict[str, Any], key: str) -> dict[str, Any]:
    relative = probe.get(key)
    if not relative:
        raise ValueError(f"probe {probe.get('probe_id')} lacks {key}")
    return json.loads((root / relative).read_text())


def load_cases(
    root: str | Path,
    *,
    include_findings: bool = True,
    rejected_sample: int = 0,
    rng_seed: int = 0,
) -> list[ReviewCase]:
    """Load minimized findings and a reproducible sample of rejected divergences."""
    root = Path(root)
    cases: list[ReviewCase] = []
    if include_findings:
        for finding in _read_jsonl(root / "findings.jsonl"):
            report_path = root / "reports" / f"{finding['id']}.json"
            if not report_path.exists():
                continue
            cases.append(
                ReviewCase(
                    case_id=f"finding-{finding['id']}",
                    finding_id=finding["id"],
                    probe_id=finding.get("origin_probe_id"),
                    spec=finding["spec"],
                    report=json.loads(report_path.read_text()),
                )
            )
    rejected = [
        p
        for p in _read_jsonl(root / "probes.jsonl")
        if p.get("verdict") == "DIVERGENCE"
        and p.get("category") != "bug_candidate"
        and p.get("spec_path")
        and p.get("report_path")
    ]
    rejected.sort(key=lambda p: p["probe_id"])
    if rejected_sample > len(rejected):
        rejected_sample = len(rejected)
    selected = random.Random(rng_seed).sample(rejected, rejected_sample)
    for probe in selected:
        cases.append(
            ReviewCase(
                case_id=f"probe-{probe['probe_id']}",
                probe_id=probe["probe_id"],
                spec=_artifact(root, probe, "spec_path"),
                report=_artifact(root, probe, "report_path"),
                origin="rejected_probe",
            )
        )
    return cases


def _known_differences() -> list[dict[str, Any]]:
    return json.loads((files("agent") / "data" / "known_differences.json").read_text())


def _historical_records(root: Path) -> list[dict[str, Any]]:
    raw = root / "agent" / "data" / "bug_corpus" / "raw"
    records: list[dict[str, Any]] = []
    for name in ("solang_issues.json", "solang_fix_prs.json"):
        path = raw / name
        if not path.exists():
            continue
        for item in json.loads(path.read_text()):
            records.append(
                {
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "state": item.get("state") or item.get("closedAt"),
                    "text": (item.get("body") or "")[:1200],
                }
            )
    path = raw / "solang_changelog_fixed.json"
    if path.exists():
        for item in json.loads(path.read_text()):
            records.append(
                {
                    "title": f"CHANGELOG {item.get('version', '')}",
                    "url": "",
                    "state": "fixed",
                    "text": (item.get("text") or "")[:1200],
                }
            )
    return records


def relevant_history(
    case: ReviewCase, records: list[dict[str, Any]], limit: int = 8
) -> list[dict[str, Any]]:
    """Small deterministic lexical retrieval; no embeddings or new dependencies."""
    text = json.dumps(
        {
            "name": case.spec.get("name"),
            "source": case.spec.get("solidity", ""),
            "kinds": [d.get("kind") for d in case.report.get("divergences", [])],
        }
    ).lower()
    words = {
        w
        for w in re.findall(r"[a-z][a-z0-9_]{3,}", text)
        if w
        not in {
            "function",
            "public",
            "return",
            "returns",
            "contract",
            "solidity",
            "pragma",
            "state",
            "external",
        }
    }

    def score(record: dict[str, Any]) -> tuple[int, str]:
        haystack = f"{record['title']} {record['text']}".lower()
        return (-sum(w in haystack for w in words), record.get("url", ""))

    return sorted(records, key=score)[:limit]


def _case_payload(case: ReviewCase) -> dict[str, Any]:
    return {
        "case_id": case.case_id,
        "origin": case.origin,
        "spec": case.spec,
        "verdict": case.report.get("verdict"),
        "earliest_divergence": case.report.get("earliest_divergence"),
        "divergences": case.report.get("divergences", []),
    }


def _validate_panel(d: dict[str, Any]) -> list[str]:
    problems = []
    if d.get("category") not in CATEGORIES:
        problems.append(f"category must be one of {sorted(CATEGORIES)}")
    if d.get("confidence") not in ("high", "medium", "low"):
        problems.append("confidence must be high|medium|low")
    for key in ("evidence", "rationale", "cluster_hint"):
        if not isinstance(d.get(key), str) or not d[key]:
            problems.append(f"{key} must be a non-empty string")
    if not isinstance(d.get("historical_match_url"), str):
        problems.append("historical_match_url must be a string")
    return problems


def _validate_adversarial(d: dict[str, Any]) -> list[str]:
    problems = []
    if not isinstance(d.get("rebuttal_succeeds"), bool):
        problems.append("rebuttal_succeeds must be boolean")
    if d.get("category") not in CATEGORIES:
        problems.append(f"category must be one of {sorted(CATEGORIES)}")
    for key in ("evidence", "rationale"):
        if not isinstance(d.get(key), str) or not d[key]:
            problems.append(f"{key} must be a non-empty string")
    if not isinstance(d.get("historical_match_url"), str):
        problems.append("historical_match_url must be a string")
    return problems


def screen_case(
    client: ChatClient,
    case: ReviewCase,
    *,
    judges: int,
    known_differences: list[dict[str, Any]],
    history: list[dict[str, Any]],
) -> dict[str, Any]:
    if judges < 1:
        raise ValueError("judges must be positive")
    payload = _case_payload(case)
    known_json = json.dumps(known_differences, indent=2)
    history_json = json.dumps(history, indent=2)
    panel = []
    for _ in range(judges):
        panel.append(
            client.chat_json(
                "You are an offline differential-testing adjudicator. Return JSON only.",
                load_prompt("adjudicate").substitute(
                    known_differences_json=known_json,
                    historical_records_json=history_json,
                    case_json=json.dumps(payload, indent=2),
                ),
                validate=_validate_panel,
                stage="adjudicate",
            )
        )
    votes = sum(j["category"] == "bug_candidate" for j in panel)
    panel_survives = votes > judges / 2
    adversarial = None
    if panel_survives:
        adversarial = client.chat_json(
            "You are an adversarial bug-review skeptic. Return JSON only.",
            load_prompt("adversarial").substitute(
                known_differences_json=known_json,
                historical_records_json=history_json,
                case_json=json.dumps(payload, indent=2),
                panel_json=json.dumps(panel, indent=2),
            ),
            validate=_validate_adversarial,
            stage="adjudicate_adversarial",
        )
    survives = panel_survives and not adversarial["rebuttal_succeeds"]
    return {
        "case_id": case.case_id,
        "probe_id": case.probe_id,
        "finding_id": case.finding_id,
        "origin": case.origin,
        "ts": time.time(),
        "panel": panel,
        "panel_bug_votes": votes,
        "adversarial": adversarial,
        "status": "survivor" if survives else "rejected",
        "survives": survives,
        "cluster_hint": next(
            (j["cluster_hint"] for j in panel if j["category"] == "bug_candidate"),
            None,
        ),
        "historical_match_urls": sorted(
            {
                j["historical_match_url"]
                for j in [*panel, *([adversarial] if adversarial else [])]
                if j["historical_match_url"]
            }
        ),
    }


def _replay_and_reduce(
    case: ReviewCase, cfg: AgentConfig, client: ChatClient
) -> dict[str, Any]:
    """Reverify a survivor; rejected probes additionally receive reduction."""
    runs = 0

    def run(spec: dict[str, Any]) -> dict[str, Any]:
        nonlocal runs
        runs += 1
        return run_spec_dict(spec)

    report = run(case.spec)
    result: dict[str, Any] = {
        "verdict": report.get("verdict"),
        "earliest_signature": earliest_signature(report),
        "tool_versions": report.get("tool_versions", {}),
        "oracle_runs": runs,
    }
    original_sig = earliest_signature(case.report)
    if (
        report.get("verdict") != "DIVERGENCE"
        or earliest_signature(report) != original_sig
    ):
        result["stable"] = False
        return result
    result["stable"] = True
    if case.origin != "rejected_probe":
        return result
    small_spec, minimality = minimize(
        case.spec,
        report,
        run,
        client,
        config=ReduceConfig.from_agent_config(cfg),
    )
    small_report = run(small_spec)
    result["minimality"] = minimality
    result["reduced_signature"] = earliest_signature(small_report)
    result["reduction_stable"] = earliest_signature(small_report) == original_sig
    result["review_spec"] = small_spec
    result["review_report"] = small_report
    result["oracle_runs"] = runs
    return result


def _write_dossier(
    review_dir: Path,
    case: ReviewCase,
    record: dict[str, Any],
    history: list[dict[str, Any]],
) -> None:
    dossier_dir = review_dir / "dossiers" / case.case_id
    dossier_dir.mkdir(parents=True, exist_ok=True)
    payload = {"case": _case_payload(case), "screening": record, "history": history}
    replay = record.get("replay") or {}
    if replay.get("review_spec") is not None:
        (dossier_dir / "spec.review.json").write_text(
            json.dumps(replay["review_spec"], indent=2) + "\n"
        )
        (dossier_dir / "report.review.json").write_text(
            json.dumps(replay["review_report"], indent=2) + "\n"
        )
        # Keep the JSON dossier compact; full review artifacts sit beside it.
        replay = {k: v for k, v in replay.items() if not k.startswith("review_")}
        payload["screening"] = {**record, "replay": replay}
    (dossier_dir / "dossier.json").write_text(json.dumps(payload, indent=2) + "\n")
    display_spec = replay.get("review_spec") or case.spec
    lines = [
        f"# Review {case.case_id}",
        "",
        f"Status: **{record['status']}**; origin: `{case.origin}`",
        "",
        "## Minimized/current spec",
        "",
        "```solidity",
        display_spec.get("solidity", ""),
        "```",
        "",
        "## Earliest divergence",
        "",
        "```json",
        json.dumps(case.report.get("earliest_divergence"), indent=2),
        "```",
        "",
        "## Panel",
        "",
        "```json",
        json.dumps(record["panel"], indent=2),
        "```",
        "",
        "## Adversarial review",
        "",
        "```json",
        json.dumps(record.get("adversarial"), indent=2),
        "```",
        "",
        "## Potentially relevant historical records",
        "",
    ]
    lines.extend(f"- {r['title']}: {r['url']}" for r in history)
    lines.extend(
        [
            "",
            "Human semantic review and a current open+closed upstream search are required before counting this as a new bug.",
        ]
    )
    (dossier_dir / "dossier.md").write_text("\n".join(lines) + "\n")


def adjudicate_cases(
    client: ChatClient,
    cfg: AgentConfig,
    root: str | Path,
    cases: list[ReviewCase],
    *,
    judges: int = 2,
    replay_promoted: bool = False,
    repo_root: str | Path | None = None,
) -> dict[str, int]:
    root = Path(root)
    review_dir = root / "review"
    output = review_dir / "screening.jsonl"
    completed = {
        r["case_id"] for r in _read_jsonl(output) if isinstance(r.get("survives"), bool)
    }
    history_records = _historical_records(
        Path(repo_root) if repo_root else Path(__file__).resolve().parents[3]
    )
    known = _known_differences()
    counts = {"survivor": 0, "rejected": 0, "error": 0, "skipped": 0}
    for case in cases:
        if case.case_id in completed:
            counts["skipped"] += 1
            continue
        history = relevant_history(case, history_records)
        usage_mark = client.usage_marker()
        try:
            record = screen_case(
                client,
                case,
                judges=judges,
                known_differences=known,
                history=history,
            )
            record["prompt_version"] = 1
            record["model"] = cfg.model
            record["temperature"] = cfg.temperature
            if record["survives"] and replay_promoted:
                record["replay"] = _replay_and_reduce(case, cfg, client)
            record["usage"] = client.usage_since(usage_mark)["totals"]
            if record["survives"]:
                _write_dossier(review_dir, case, record, history)
            _append_jsonl(output, record)
            counts[record["status"]] += 1
        except (LLMError, OSError, ValueError) as e:
            _append_jsonl(
                output,
                {
                    "case_id": case.case_id,
                    "ts": time.time(),
                    "status": "error",
                    "error": f"{type(e).__name__}: {e}",
                    "usage": client.usage_since(usage_mark)["totals"],
                },
            )
            counts["error"] += 1
    return counts
