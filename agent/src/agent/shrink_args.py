"""Deterministic argument shrinking (T1.4).

Candidate generators per step arg, most-shrunk first:

    ints      -> [0, 1] (+ [-1] for negatives)
    strings   -> ["", "a"]
    bytes     -> ["0x", first-half]
    addresses -> canonical $labels ("$alice")
    bools     -> [false]
    arrays    -> [[], [first]]
    tuples    -> element-wise one-notch shrinks

`shrink_candidates(spec)` yields (step_index, arg_index, new_value) triples;
each candidate is verified by the reducer's oracle predicate. One notch per
candidate — iterated application reaches the fixed point.
"""

from __future__ import annotations

import re
from typing import Any

_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_LABEL_RE = re.compile(r"^\$[a-z]+$")


def value_candidates(v: Any) -> list[Any]:
    """Shrunk replacements for one arg value, most-shrunk first (excludes v)."""
    out: list[Any] = []
    if isinstance(v, bool):
        out = [False]
    elif isinstance(v, int):
        out = [0, 1] + ([-1] if v < 0 else [])
    elif isinstance(v, str):
        if _LABEL_RE.match(v):
            out = []  # already canonical
        elif _ADDRESS_RE.match(v):
            out = ["$alice"]  # canonical label for any raw address
        elif v.startswith("0x"):
            raw = v[2:]
            out = ["0x"] + (["0x" + raw[: len(raw) // 2]] if len(raw) > 2 else [])
        else:
            out = ["", "a"]
    elif isinstance(v, list):
        out = [[]] + ([[v[0]]] if len(v) > 1 else [])
    if isinstance(v, (list, tuple)) and v:
        for i, item in enumerate(v):
            for sub in value_candidates(item):
                cand = list(v)
                cand[i] = sub
                out.append(cand)
    seen: set[str] = set()
    result = []
    for cand in out:
        key = repr(cand)
        if key not in seen and cand != v:
            seen.add(key)
            result.append(cand)
    return result


def rank(v: Any) -> int:
    """Shrink rank: strictly lower means strictly simpler. Used to reject
    lateral moves (accepting rank-equivalent candidates would ping-pong)."""
    if isinstance(v, bool):
        return 0 if v is False else 1
    if isinstance(v, int):
        return {0: 0, 1: 1, -1: 1}.get(v, 2)
    if isinstance(v, str):
        if _LABEL_RE.match(v):
            return 0
        if v.startswith("0x"):
            return 0 if v == "0x" else 1 + (len(v) - 2) // 2
        return {"": 0, "a": 1}.get(v, 2 + len(v))
    if isinstance(v, (list, tuple)):
        return 10 * len(v) + sum(rank(x) for x in v)
    return 99


def shrink_candidates(spec: dict[str, Any]):
    """Yield (step_index, arg_index, new_value) for every shrinkable arg —
    strictly rank-decreasing candidates only."""
    for i, step in enumerate(spec.get("steps", [])):
        for j, arg in enumerate(step.get("args", [])):
            for cand in value_candidates(arg):
                if rank(cand) < rank(arg):
                    yield (i, j, cand)


def with_arg(spec: dict[str, Any], step_index: int, arg_index: int, value: Any) -> dict:
    """Return a deep-copied spec with one arg replaced."""
    import copy

    out = copy.deepcopy(spec)
    out["steps"][step_index]["args"][arg_index] = value
    return out
