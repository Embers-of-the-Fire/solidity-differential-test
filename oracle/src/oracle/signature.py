"""Divergence signatures: a stable, structural identity for "same bug".

A witness is identified by the signature of its *earliest* divergence —
strict at the causal head, tolerant of downstream consequences (reduction may
legitimately drop secondary divergences):

    point     = "compile" | "deploy" | <step index>
    signature = "<kind>|<point>|<function-or-empty>|<relation>"

`relation` is a per-kind *structural* descriptor of the two normalized
payloads — deliberately not the values themselves, because argument shrinking
changes values without changing the bug:

    COMPILE_ASYMMETRY              solc-rejects | solang-rejects
    DEPLOY_MISMATCH                <evm-status>≠<polkadot-status>
    STATUS_MISMATCH                <status-a>≠<status-b>
    TX_STATUS_MISMATCH             <status-a>≠<status-b>
    RETURN_MISMATCH                type-shape pair, e.g. int≠int, tuple[2]≠int
    REASON_MISMATCH                reason-class pair: none | error-string | panic:<hexcode>
    EVENT_MISMATCH                 first structural difference: count | name | args
    STORAGE_MISMATCH               multiset(count) | map(exact), tagged with the mode
    GAS_MISMATCH                   value (opt-in kind; gas models are incomparable)

The functions here are pure: no I/O, no chain or compiler interaction.
"""

from __future__ import annotations

import re
from typing import Any

POINT_COMPILE = "compile"
POINT_DEPLOY = "deploy"

_PANIC_RE = re.compile(r"^Panic\((0x[0-9a-fA-F]+)\)$")
_PANIC_SELECTOR = "4e487b71"


def value_shape(v: Any) -> str:
    """Type-shape of a norm_value() payload (values are irrelevant)."""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "int"
    if isinstance(v, str):
        return "bytes" if v.startswith("0x") else "string"
    if isinstance(v, (list, tuple)):
        return f"tuple[{len(v)}]"
    if isinstance(v, dict):
        return "struct"
    return type(v).__name__


def reason_class(reason: Any) -> str:
    """Classify a revert reason payload: none | error-string | panic:<hexcode>.

    Handles the decoded forms ("Panic(0x11)", plain strings) as well as raw
    revert-data hex carrying the Panic(uint256) selector (EVM 32-byte word or
    SCALE little-endian tail), which compare.py substitutes when no decoded
    reason is available.
    """
    if reason is None or reason == "":
        return "none"
    s = str(reason)
    m = _PANIC_RE.match(s)
    if m:
        return f"panic:{m.group(1).lower()}"
    if s.startswith("0x") and s[2:10].lower() == _PANIC_SELECTOR:
        tail = s[10:]
        try:
            raw = bytes.fromhex(tail)
            if len(raw) == 32:  # EVM ABI word, big-endian
                code = int.from_bytes(raw, "big")
            else:  # solang/SCALE: unpadded little-endian
                code = int.from_bytes(raw, "little")
            return f"panic:{code:#04x}"
        except ValueError:
            pass
    return "error-string"


def _event_relation(evm_events: Any, polkadot_events: Any) -> str:
    """First structural difference between two event lists."""
    a = evm_events if isinstance(evm_events, list) else []
    b = polkadot_events if isinstance(polkadot_events, list) else []
    if len(a) != len(b):
        return "count"
    for ea, eb in zip(a, b, strict=False):
        if (ea or {}).get("name") != (eb or {}).get("name"):
            return "name"
        va = [x.get("value") for x in (ea or {}).get("args", [])]
        vb = [x.get("value") for x in (eb or {}).get("args", [])]
        if va != vb:
            return "args"
    return "count"  # unreachable in practice (equal lists do not diverge)


def _status_pair(evm: Any, polkadot: Any) -> str:
    def status_of(v: Any) -> str:
        if isinstance(v, dict):
            return str(v.get("status"))
        return str(v)

    return f"{status_of(evm)}≠{status_of(polkadot)}"


def relation_for(kind: str, evm: Any, polkadot: Any) -> str:
    """Structural relation descriptor for one divergence kind's payloads.

    `evm` / `polkadot` are the normalized payloads as stored on the Divergence
    (post norm_value); unknown kinds fall back to a value-free marker.
    """
    if kind == "COMPILE_ASYMMETRY":
        solc_ok = bool((evm or {}).get("solc_ok"))
        return "solang-rejects" if solc_ok else "solc-rejects"
    if kind == "DEPLOY_MISMATCH":
        return _status_pair(evm, polkadot)
    if kind in ("STATUS_MISMATCH", "TX_STATUS_MISMATCH"):
        return _status_pair(evm, polkadot)
    if kind == "RETURN_MISMATCH":
        return f"{value_shape(evm)}≠{value_shape(polkadot)}"
    if kind == "REASON_MISMATCH":
        return f"{reason_class(evm)}≠{reason_class(polkadot)}"
    if kind == "EVENT_MISMATCH":
        return _event_relation(evm, polkadot)
    if kind == "STORAGE_MISMATCH":
        # count-mode summaries are {"nonzero_entries", "values"} dicts; exact
        # mode is a raw slot->value map. Tagged with the originating mode.
        count_shaped = lambda v: isinstance(v, dict) and "values" in v  # noqa: E731
        if count_shaped(evm) or count_shaped(polkadot):
            return "multiset(count)"
        return "map(exact)"
    if kind == "GAS_MISMATCH":
        return "value"
    return "structural"


def format_signature(
    kind: str, point: str | int, function: str | None, relation: str
) -> str:
    """Canonical signature string: "<kind>|<point>|<function-or-empty>|<relation>"."""
    return f"{kind}|{point}|{function or ''}|{relation}"


def make_signature(
    kind: str, point: str | int, function: str | None, evm: Any, polkadot: Any
) -> str:
    """Compute the full signature for a divergence and its payloads."""
    return format_signature(kind, point, function, relation_for(kind, evm, polkadot))


def parse_signature(signature: str) -> dict[str, Any]:
    """Inverse of format_signature (point stays a string; '' function -> None)."""
    kind, point, function, relation = (signature.split("|", 3) + ["", "", "", ""])[:4]
    return {
        "kind": kind,
        "point": point,
        "function": function or None,
        "relation": relation,
    }
