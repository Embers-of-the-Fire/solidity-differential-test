"""Spec generation: prompt building + structural validation of LLM specs.

Validation here is intentionally stricter than the oracle's loader: it also
enforces agent-side constraints (inline source, no struct args, step budget)
that would otherwise waste an expensive oracle run.
"""

from __future__ import annotations

import re
from typing import Any

from .hypotheses import render_for_prompt
from .llm import ChatClient
from .prompts import load_prompt
from .seeds import Seed

SENDERS = {"deployer", "alice", "bob", "charlie"}
MAX_STEPS = 8
MAX_SOURCE_LINES = 120
RECENT_PROBES_IN_PROMPT = 8


def _args_ok(args: Any) -> bool:
    """Args must be JSON scalars, hex/label strings or (nested) arrays.

    Dicts are rejected: the oracle cannot encode struct/tuple arguments.
    """
    if args is None or isinstance(args, (bool, int, float, str)):
        return True
    if isinstance(args, list):
        return all(_args_ok(a) for a in args)
    return False


def _function_declared(fn: str, source: str) -> bool:
    """True if `fn` is a declared function or a public state variable getter."""
    return bool(
        re.search(rf"\bfunction\s+{re.escape(fn)}\b", source)
        or re.search(rf"\bpublic\s+{re.escape(fn)}\b", source)
    )


def validate_spec_dict(d: dict[str, Any]) -> list[str]:
    """Return a list of problems (empty = usable)."""
    problems: list[str] = []

    source = d.get("solidity")
    if not isinstance(source, str) or "contract" not in source:
        problems.append("missing or invalid 'solidity' inline source string")
    elif source.count("\n") > MAX_SOURCE_LINES:
        problems.append(f"source too long (>{MAX_SOURCE_LINES} lines); keep it small")
    if "source_file" in d:
        problems.append("use inline 'solidity', not 'source_file'")

    contract = d.get("contract")
    if not isinstance(contract, str) or not contract.isidentifier():
        problems.append("'contract' must be a valid Solidity contract name")
    elif isinstance(source, str) and f"contract {contract}" not in source:
        problems.append(f"'contract' name {contract!r} not declared in the source")

    ctor = d.get("constructor", {})
    if not isinstance(ctor, dict) or not _args_ok(ctor.get("args", [])):
        problems.append("'constructor.args' must be JSON scalars/arrays (no objects)")

    steps = d.get("steps")
    if not isinstance(steps, list) or not steps:
        problems.append("'steps' must be a non-empty array")
    elif len(steps) > MAX_STEPS:
        problems.append(f"too many steps ({len(steps)} > {MAX_STEPS})")
    else:
        for i, s in enumerate(steps):
            if not isinstance(s, dict):
                problems.append(f"step {i}: must be an object")
                continue
            if s.get("action", "call") not in ("call", "query"):
                problems.append(f"step {i}: action must be 'call' or 'query'")
            fn = s.get("function")
            if not isinstance(fn, str) or not fn:
                problems.append(f"step {i}: missing 'function'")
            elif isinstance(source, str) and not _function_declared(fn, source):
                problems.append(f"step {i}: function {fn!r} not declared in source")
            if s.get("sender", "deployer") not in SENDERS:
                problems.append(f"step {i}: sender must be one of {sorted(SENDERS)}")
            if not _args_ok(s.get("args", [])):
                problems.append(
                    f"step {i}: args must be JSON scalars/arrays (no objects)"
                )
            v = s.get("value", 0)
            if not isinstance(v, int) or isinstance(v, bool) or v < 0 or v > 10**15:
                problems.append(f"step {i}: value must be an int in [0, 10**15]")

    storage = d.get("oracle", {}).get("storage", "count")
    if storage not in ("count", "exact", "off"):
        problems.append("oracle.storage must be 'count', 'exact' or 'off'")
    if d.get("oracle", {}).get("gas"):
        problems.append("oracle.gas must be false (gas models are incomparable)")

    return problems


def _memory_digest(recent: list[dict[str, Any]]) -> str:
    if not recent:
        return "(none yet)"
    lines = []
    for p in recent:
        kinds = ",".join(p.get("kinds") or []) or "-"
        lines.append(
            f"- {p.get('name')} [{p.get('seed')}] -> {p.get('verdict')}/{p.get('category')} ({kinds})"
        )
    return "\n".join(lines)


def build_generation_prompt(
    seed: Seed, recent: list[dict[str, Any]], notebook: dict[str, Any] | None = None
) -> tuple[str, str]:
    hints = (
        "\n".join(f"- {h}" for h in seed.hints) or "- (free exploration of the area)"
    )
    prompt = load_prompt("generate").substitute(
        id=seed.id,
        title=seed.title,
        why=seed.why,
        hints=hints,
        hypotheses=render_for_prompt(notebook)
        if notebook
        else "(no hypotheses yet — your probe should establish one)",
        memory=_memory_digest(recent[-RECENT_PROBES_IN_PROMPT:]),
    )
    system = (
        "You design differential-testing probes for Solidity compilers. "
        "You reply with a single JSON object and nothing else."
    )
    return system, prompt


def generate_spec(
    client: ChatClient,
    seed: Seed,
    recent: list[dict[str, Any]],
    notebook: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Ask the model for one validated spec dict."""
    system, user = build_generation_prompt(seed, recent, notebook)
    spec = client.chat_json(system, user, validate=validate_spec_dict, stage="generate")
    spec.setdefault("oracle", {})
    spec["oracle"].setdefault("storage", "count")
    spec["oracle"]["gas"] = False  # hard rule: gas models are incomparable
    return spec
