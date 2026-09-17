"""Cross-round hypothesis notebooks: the loop's durable memory.

One notebook per seed area, persisted at `findings/hypotheses/<seed_id>.json`.
After every probe the reflect step updates the notebook; the next generation
prompt for that seed carries its open hypotheses and their `next_probe`
intents, turning myopic rounds into a confirm/refute cycle.

Notebook schema:

    {
      "seed_id": "int-semantics",
      "hypotheses": [
        {"id": "h1", "statement": "...", "status": "open",
         "confidence": "medium",
         "evidence": [{"probe": "name", "verdict": "...", "note": "..."}],
         "next_probe": "..."}
      ],
      "updated_ts": 1758...
    }

Status transitions: open -> confirmed | refuted (both terminal).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

MAX_OPEN_HYPOTHESES = 8
VALID_OPS = {"add", "confirm", "refute", "refine", "retarget"}
TERMINAL = {"confirmed", "refuted"}


def empty_notebook(seed_id: str) -> dict[str, Any]:
    return {"seed_id": seed_id, "hypotheses": [], "updated_ts": None}


def notebook_path(findings_dir: str | Path, seed_id: str) -> Path:
    return Path(findings_dir) / "hypotheses" / f"{seed_id}.json"


def load_notebook(findings_dir: str | Path, seed_id: str) -> dict[str, Any]:
    path = notebook_path(findings_dir, seed_id)
    if not path.exists():
        return empty_notebook(seed_id)
    return json.loads(path.read_text())


def save_notebook(findings_dir: str | Path, notebook: dict[str, Any]) -> None:
    path = notebook_path(findings_dir, notebook["seed_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    notebook["updated_ts"] = time.time()
    path.write_text(json.dumps(notebook, indent=2))


def _find(notebook: dict[str, Any], hid: str) -> dict[str, Any] | None:
    for h in notebook["hypotheses"]:
        if h["id"] == hid:
            return h
    return None


def _next_id(notebook: dict[str, Any]) -> str:
    used = {h["id"] for h in notebook["hypotheses"]}
    n = 1
    while f"h{n}" in used:
        n += 1
    return f"h{n}"


def _open_count(notebook: dict[str, Any]) -> int:
    return sum(1 for h in notebook["hypotheses"] if h["status"] == "open")


def _evidence_entry(evidence: dict[str, Any] | None) -> dict[str, Any]:
    evidence = evidence or {}
    return {
        "probe": str(evidence.get("probe", "")),
        "verdict": str(evidence.get("verdict", "")),
        "note": str(evidence.get("note", "")),
    }


def validate_op(notebook: dict[str, Any], op: dict[str, Any]) -> str | None:
    """Return a problem string, or None if the op is applicable."""
    kind = op.get("op")
    if kind not in VALID_OPS:
        return f"unknown op {kind!r} (valid: {sorted(VALID_OPS)})"

    if kind == "add":
        if not isinstance(op.get("statement"), str) or not op["statement"].strip():
            return "add: 'statement' must be a non-empty string"
        if not isinstance(op.get("next_probe"), str) or not op["next_probe"].strip():
            return "add: 'next_probe' must be a non-empty string"
        if _open_count(notebook) >= MAX_OPEN_HYPOTHESES:
            return f"add: open-hypothesis cap reached ({MAX_OPEN_HYPOTHESES}); resolve some first"
        return None

    target = _find(notebook, str(op.get("id", "")))
    if target is None:
        return f"{kind}: hypothesis {op.get('id')!r} does not exist"
    if target["status"] in TERMINAL and kind != "retarget":
        return f"{kind}: {target['id']} is already {target['status']} (terminal)"

    if kind in ("confirm", "refute"):
        return None  # evidence is optional; status flip is the payload
    if kind == "refine":
        if not isinstance(op.get("statement"), str) or not op["statement"].strip():
            return "refine: 'statement' must be a non-empty string"
        return None
    if kind == "retarget":
        if not isinstance(op.get("next_probe"), str) or not op["next_probe"].strip():
            return "retarget: 'next_probe' must be a non-empty string"
        return None
    return None


def apply_op(notebook: dict[str, Any], op: dict[str, Any]) -> dict[str, Any]:
    """Apply a pre-validated op. Mutates and returns the notebook."""
    kind = op["op"]
    evidence = _evidence_entry(op.get("evidence"))
    if kind == "add":
        notebook["hypotheses"].append(
            {
                "id": _next_id(notebook),
                "statement": op["statement"].strip(),
                "status": "open",
                "confidence": op.get("confidence", "medium")
                if op.get("confidence") in ("high", "medium", "low")
                else "medium",
                "evidence": [evidence] if evidence["probe"] else [],
                "next_probe": op["next_probe"].strip(),
            }
        )
        return notebook
    target = _find(notebook, str(op["id"]))
    assert target is not None  # guaranteed by validate_op
    if evidence["probe"]:
        target["evidence"].append(evidence)
    if kind == "confirm":
        target["status"] = "confirmed"
    elif kind == "refute":
        target["status"] = "refuted"
    elif kind == "refine":
        target["statement"] = op["statement"].strip()
    elif kind == "retarget":
        target["next_probe"] = op["next_probe"].strip()
    return notebook


def apply_ops(
    notebook: dict[str, Any], ops: list[Any]
) -> tuple[dict[str, Any], list[str]]:
    """Apply valid ops in order; return (notebook, rejected-op problems).

    `ops` is untrusted LLM output: non-dict entries are rejected, not fatal.
    """
    rejected = []
    for op in ops:
        if not isinstance(op, dict):
            rejected.append(f"op is not an object: {op!r:.80}")
            continue
        problem = validate_op(notebook, op)
        if problem:
            rejected.append(problem)
        else:
            apply_op(notebook, op)
    return notebook, rejected


def render_for_prompt(notebook: dict[str, Any]) -> str:
    """The '# Current hypotheses' section of the generation prompt."""
    if not notebook["hypotheses"]:
        return "(no hypotheses yet — your probe should establish one)"
    lines = []
    for h in notebook["hypotheses"]:
        if h["status"] == "open":
            lines.append(
                f"- [open] {h['id']}: {h['statement']}\n  NEXT PROBE: {h['next_probe']}"
            )
        elif h["status"] == "confirmed":
            lines.append(f"- [confirmed] {h['id']}: {h['statement']} (established)")
        else:
            lines.append(
                f"- [refuted] {h['id']}: {h['statement']} (do NOT re-test this)"
            )
    return "\n".join(lines)


def summary_counts(notebooks: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"open": 0, "confirmed": 0, "refuted": 0}
    for nb in notebooks:
        for h in nb["hypotheses"]:
            counts[h["status"]] += 1
    return counts
