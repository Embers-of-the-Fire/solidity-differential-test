"""Triage: classify a diverging report as known_semantic / oracle_artifact /
bug_candidate / invalid_probe.

Cheap deterministic rules run first (documented platform differences, the
storage-count heuristic); anything unresolved goes to one LLM triage call.
"""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any

from .executor import divergence_kinds
from .llm import ChatClient, LLMError
from .prompts import load_prompt

VALID_CATEGORIES = {
    "known_semantic",
    "oracle_artifact",
    "bug_candidate",
    "invalid_probe",
}


def _known_rules() -> list[dict[str, Any]]:
    return json.loads((files("agent") / "data" / "known_differences.json").read_text())


def classify_by_rules(divergence: dict[str, Any], source: str) -> str | None:
    """Deterministic pre-classification; None = needs the LLM."""
    kind = divergence.get("kind")
    for rule in _known_rules():
        if kind not in rule["kinds"]:
            continue
        markers = rule["source_markers"]
        if not markers or any(m in source for m in markers):
            return "known_semantic"
    return None


def _validate_triage(d: dict[str, Any]) -> list[str]:
    problems = []
    if d.get("category") not in VALID_CATEGORIES:
        problems.append(f"'category' must be one of {sorted(VALID_CATEGORIES)}")
    if d.get("confidence") not in ("high", "medium", "low"):
        problems.append("'confidence' must be high|medium|low")
    for key in ("rationale", "blame", "summary"):
        if not isinstance(d.get(key), str) or not d[key]:
            problems.append(f"'{key}' must be a non-empty string")
    return problems


def triage_report(
    client: ChatClient, spec_dict: dict[str, Any], report: dict[str, Any]
) -> dict[str, Any]:
    """Classify one oracle report. Never raises on LLM failure."""
    verdict = report.get("verdict")
    if verdict == "PASS":
        return {"category": "pass", "rationale": "chains agree"}
    if verdict not in ("DIVERGENCE",):
        return {
            "category": "error",
            "rationale": f"oracle run failed: {report.get('error', 'unknown')}",
        }

    source = spec_dict.get("solidity", "")
    divs = report.get("divergences", [])
    ruled = [classify_by_rules(d, source) for d in divs]
    if all(r == "known_semantic" for r in ruled):
        return {
            "category": "known_semantic",
            "confidence": "high",
            "rationale": "all divergences match documented platform differences",
            "blame": "neither",
            "summary": "; ".join(d.get("detail", "") for d in divs),
            "rule_based": True,
        }

    kinds = divergence_kinds(report)
    heuristic_note = ""
    if kinds == {"STORAGE_MISMATCH"}:
        heuristic_note = (
            "\n\nNOTE: the ONLY divergence is STORAGE_MISMATCH and the storage "
            "comparison runs in 'count' heuristic mode (zero-stripped values, "
            "keys ignored, endianness differences). Scrutinize whether this is "
            "an oracle artifact before calling it a bug."
        )

    system = (
        "You triage differential-testing findings between two Solidity toolchains. "
        "You reply with a single JSON object and nothing else."
    )
    user = (
        load_prompt("triage").substitute(
            spec_json=json.dumps(spec_dict, indent=2),
            divergences_json=json.dumps(divs, indent=2),
        )
        + heuristic_note
    )
    try:
        return client.chat_json(system, user, validate=_validate_triage, stage="triage")
    except LLMError as e:
        return {
            "category": "bug_candidate",
            "confidence": "low",
            "rationale": f"triage LLM failed ({e}); kept for manual review",
            "blame": "neither",
            "summary": "; ".join(d.get("detail", "") for d in divs),
            "triage_failed": True,
        }
