"""Reflect step: update a seed's hypothesis notebook after each probe.

Runs on every probe (per design): even a PASS is evidence against or for an
open hypothesis. LLM failures are logged and skipped — bookkeeping must never
fail the round.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .hypotheses import (
    MAX_OPEN_HYPOTHESES,
    apply_ops,
    load_notebook,
    save_notebook,
)
from .llm import ChatClient, LLMError
from .prompts import load_prompt
from .seeds import Seed


def _validate_reflect(d: dict[str, Any]) -> list[str]:
    problems = []
    ops = d.get("ops")
    if not isinstance(ops, list):
        problems.append("'ops' must be an array (possibly empty)")
    elif len(ops) > 4:
        problems.append("at most 4 ops per reflection")
    if not isinstance(d.get("reasoning"), str) or not d["reasoning"].strip():
        problems.append("'reasoning' must be a non-empty string")
    return problems


def reflect_notebook(
    client: ChatClient,
    findings_dir: str | Path,
    seed: Seed,
    spec: dict[str, Any],
    report: dict[str, Any],
    triage: dict[str, Any],
    log=print,
) -> dict[str, Any]:
    """One reflect call; returns the updated notebook (unchanged on failure)."""
    notebook = load_notebook(findings_dir, seed.id)
    system = (
        "You maintain a hypothesis notebook for differential compiler testing. "
        "You reply with a single JSON object and nothing else."
    )
    user = load_prompt("reflect").substitute(
        id=seed.id,
        title=seed.title,
        why=seed.why,
        notebook_json=json.dumps(notebook["hypotheses"], indent=2),
        spec_json=json.dumps(spec, indent=2),
        verdict=report.get("verdict"),
        category=triage.get("category"),
        divergences_json=json.dumps(report.get("divergences", []), indent=2),
        max_open=MAX_OPEN_HYPOTHESES,
    )
    try:
        out = client.chat_json(
            system, user, validate=_validate_reflect, stage="reflect"
        )
    except LLMError as e:
        log(f"[reflect] skipped: {e}")
        return notebook
    notebook, rejected = apply_ops(notebook, out["ops"])
    if rejected:
        log(f"[reflect] {len(rejected)} op(s) rejected: {'; '.join(rejected)}")
    if out["ops"]:
        save_notebook(findings_dir, notebook)
        log(f"[reflect] {len(out['ops'])} op(s) applied: {out['reasoning']}")
    return notebook
