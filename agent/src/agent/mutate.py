"""Mutation operators: produce k valid mutant specs from a corpus parent.

Two operator families:

1. Programmatic sequence-level mutators (JSON-level, zero LLM cost, valid by
   construction). Each operator is a pure `spec -> spec` function; every
   mutant is still run through `validate_spec_dict` as a belt-and-braces
   check (a failure there is an operator bug, caught in tests).
2. LLM source-level batch mutation: one call proposes n mutants from an
   explicit mutation menu. Invalid mutants are discarded and returned for
   accounting — no repair loop, because repair costs extra calls and the
   discard rate is itself an evaluation datum.

The operators are deliberately signature-blind: the only source knowledge is
what regexes give (`_function_declared`-style patterns), and numeric boundary
inference uses the literal's own magnitude, not the declared parameter type.
"""

from __future__ import annotations

import copy
import json
import random
import re
from collections.abc import Callable
from typing import Any

from .corpus import spec_id
from .generator import MAX_STEPS, SENDERS, validate_spec_dict
from .hypotheses import render_for_prompt
from .llm import ChatClient
from .prompts import load_prompt
from .seeds import Seed

_FUNC_RE = re.compile(r"\bfunction\s+([A-Za-z_]\w*)")
_PUBVAR_RE = re.compile(r"\bpublic\s+([A-Za-z_]\w*)")


def _is_call(step: dict[str, Any]) -> bool:
    return step.get("action", "call") == "call"


# --- programmatic sequence-level operators (pure: spec -> spec) --------------


def shuffle_calls(spec: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    """Swap two adjacent call steps; queries stay where they are."""
    spec = copy.deepcopy(spec)
    steps = spec.get("steps", [])
    pairs = [
        i
        for i in range(len(steps) - 1)
        if _is_call(steps[i]) and _is_call(steps[i + 1])
    ]
    if pairs:
        i = rng.choice(pairs)
        steps[i], steps[i + 1] = steps[i + 1], steps[i]
    return spec


def duplicate_step(spec: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    """Repeat a call step with perturbed args, inserted right after it."""
    spec = copy.deepcopy(spec)
    steps = spec.get("steps", [])
    calls = [i for i, s in enumerate(steps) if _is_call(s)]
    if not calls or len(steps) >= MAX_STEPS:
        return spec
    i = rng.choice(calls)
    clone = copy.deepcopy(steps[i])
    _perturb_step_args(clone, rng)
    steps.insert(i + 1, clone)
    return spec


def perturb_args(spec: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    """Perturb one argument leaf of one step."""
    spec = copy.deepcopy(spec)
    steps = [s for s in spec.get("steps", []) if s.get("args")]
    if steps:
        _perturb_step_args(rng.choice(steps), rng)
    return spec


def swap_sender(spec: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    """Replace one step's sender with another of the four allowed."""
    spec = copy.deepcopy(spec)
    steps = spec.get("steps", [])
    if steps:
        step = rng.choice(steps)
        others = sorted(SENDERS - {step.get("sender", "deployer")})
        step["sender"] = rng.choice(others)
    return spec


def insert_readback(spec: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    """Insert a zero-arg query on a public state var or a function already
    called without args, positioned after a call step."""
    spec = copy.deepcopy(spec)
    steps = spec.get("steps", [])
    source = spec.get("solidity", "")
    if not steps or len(steps) >= MAX_STEPS:
        return spec
    declared = set(_FUNC_RE.findall(source)) | set(_PUBVAR_RE.findall(source))
    zero_arg_called = {s["function"] for s in steps if not s.get("args")}
    candidates = sorted((set(_PUBVAR_RE.findall(source)) | zero_arg_called) & declared)
    if not candidates:
        return spec
    query = {"action": "query", "function": rng.choice(candidates)}
    call_idx = [i for i, s in enumerate(steps) if _is_call(s)]
    pos = rng.choice(call_idx) + 1 if call_idx else len(steps)
    steps.insert(pos, query)
    return spec


def zero_value(spec: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    """Set a step's value to 0 (never adds value: payability is unknown
    without the ABI, and 0 is always within bounds)."""
    spec = copy.deepcopy(spec)
    valued = [s for s in spec.get("steps", []) if s.get("value")]
    if valued:
        rng.choice(valued)["value"] = 0
    return spec


def _perturb_scalar(v: Any, rng: random.Random) -> Any:
    if isinstance(v, bool):
        return not v
    if isinstance(v, int):
        sign = -1 if v < 0 else 1
        k = abs(v).bit_length()
        candidates = {v + 1, v - 1, 0}
        if k:
            candidates.add(sign * (2**k - 1))
        if k >= 2:
            candidates.add(sign * 2 ** (k - 1))
        candidates.discard(v)
        return rng.choice(sorted(candidates))
    if isinstance(v, str) and v.startswith("0x") and len(v) >= 4:
        return v[:-2] + f"{rng.randrange(256):02x}"
    return v


def _perturb_step_args(step: dict[str, Any], rng: random.Random) -> None:
    """Mutate one node of a step's args tree in place."""
    args = step.get("args")
    if not isinstance(args, list) or not args:
        return
    targets: list[tuple[list[Any] | None, Any]] = []

    def walk(node: list[Any]) -> None:
        targets.append((None, node))  # the list itself: append/drop
        for idx, v in enumerate(node):
            if isinstance(v, list):
                walk(v)
            else:
                targets.append((node, idx))

    walk(args)
    container, key = rng.choice(targets)
    if container is None:
        lst = key
        if len(lst) > 1 and rng.random() < 0.5:
            lst.pop(rng.randrange(len(lst)))
        else:
            lst.append(copy.deepcopy(lst[-1]))
    else:
        container[key] = _perturb_scalar(container[key], rng)


_OPERATORS: list[Callable[[dict[str, Any], random.Random], dict[str, Any]]] = [
    shuffle_calls,
    duplicate_step,
    perturb_args,
    swap_sender,
    insert_readback,
    zero_value,
]


def programmatic_mutants(
    parent_spec: dict[str, Any],
    rng: random.Random,
    *,
    k: int,
    ops_per_mutant: int,
) -> tuple[list[dict[str, Any]], int]:
    """Build up to k mutants via weighted random operator composition.

    Returns (mutants, operator_failures): mutants are deduplicated against the
    parent and each other (content-derived id); a validator failure is an
    operator bug and is counted, never silently shipped.
    """
    parent_body = {kk: vv for kk, vv in parent_spec.items() if kk != "meta"}
    mutants: list[dict[str, Any]] = []
    failures = 0
    seen = {spec_id(parent_body)}
    for _ in range(k):
        m = copy.deepcopy(parent_body)
        for _ in range(max(1, ops_per_mutant)):
            op = rng.choice(_OPERATORS)
            m = op(m, rng)
        if validate_spec_dict(m):
            failures += 1
            continue
        sid = spec_id(m)
        if sid in seen:
            continue
        seen.add(sid)
        mutants.append(m)
    return mutants, failures


# --- LLM source-level batch mutation ------------------------------------------


def _validate_mutants_envelope(d: dict[str, Any]) -> list[str]:
    problems = []
    muts = d.get("mutants")
    if not isinstance(muts, list) or not muts:
        problems.append("'mutants' must be a non-empty array of spec objects")
    elif not all(isinstance(m, dict) for m in muts):
        problems.append("each mutant must be a JSON object (a full spec)")
    return problems


def llm_mutants(
    client: ChatClient,
    parent_spec: dict[str, Any],
    parent_outcome: str,
    seed: Seed,
    notebook: dict[str, Any],
    n: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """One LLM call proposes n mutants; returns (valid, invalid).

    The envelope is repaired via the usual validate-and-repair loop, but
    individual mutants are validated once and discarded when broken — no
    per-mutant repair, the discard count is an evaluation datum.
    """
    system = (
        "You mutate existing differential-testing probes between two Solidity "
        "toolchains. You reply with a single JSON object and nothing else."
    )
    hints = (
        "\n".join(f"- {h}" for h in seed.hints) or "- (free exploration of the area)"
    )
    user = load_prompt("mutate").substitute(
        id=seed.id,
        title=seed.title,
        why=seed.why,
        hints=hints,
        hypotheses=render_for_prompt(notebook),
        parent_outcome=parent_outcome,
        parent_spec_json=json.dumps(parent_spec, indent=2),
        n=n,
    )
    out = client.chat_json(
        system, user, validate=_validate_mutants_envelope, stage="mutate"
    )
    valid: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []
    parent_body = {kk: vv for kk, vv in parent_spec.items() if kk != "meta"}
    seen = {spec_id(parent_body)}
    for cand in out["mutants"]:
        body = {kk: vv for kk, vv in cand.items() if kk != "meta"}
        if validate_spec_dict(body):
            invalid.append(cand)
            continue
        body.setdefault("oracle", {})
        body["oracle"].setdefault("storage", "count")
        body["oracle"]["gas"] = False  # hard rule: gas models are incomparable
        sid = spec_id(body)
        if sid in seen:
            continue
        seen.add(sid)
        valid.append(body)
    return valid, invalid
