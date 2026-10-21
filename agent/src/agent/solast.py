"""solc-AST-guided source deletion candidates (T1.3).

Uses `solc --ast-compact-json` (devshell binary, no new dependencies) on a temp
file; node `src` triples (`offset:length:file`) give byte spans. Deletion
candidate kinds, in queue order (largest span first within each kind):

    FunctionDefinition, state VariableDeclaration, EventDefinition,
    ErrorDeclaration, ModifierDefinition, then Statement nodes inside
    surviving function bodies.

Splicing is a textual deletion of the byte span (offsets are byte offsets, so
all splicing happens on UTF-8 bytes). Two-gate verification lives in
minimize.py: gate 1 is `solc --stop-after parsing` on the candidate (~ms,
absorbs invalid splices); gate 2 is a full oracle run.

When solc itself cannot parse the *original* source (a COMPILE_ASYMMETRY
witness where solc is the rejecting side), `brace_chunks` provides the
fallback: brace-aware line chunks for the generic ddmin engine.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

# queue order of deletable top-level kinds (statements are appended last)
_KIND_ORDER = {
    "FunctionDefinition": 0,
    "VariableDeclaration": 1,
    "EventDefinition": 2,
    "ErrorDefinition": 3,
    "ModifierDefinition": 4,
}

_STATEMENT_KINDS = {
    "ExpressionStatement",
    "VariableDeclarationStatement",
    "IfStatement",
    "ForStatement",
    "WhileStatement",
    "DoWhileStatement",
    "Return",
    "EmitStatement",
    "RevertStatement",
    "Break",
    "Continue",
    "TryStatement",
    "UncheckedBlock",
}

_SKIP_FUNCTION_KINDS = {"constructor", "fallback", "receive"}


@dataclass(frozen=True)
class Span:
    offset: int  # byte offset into the UTF-8 source
    length: int
    kind: str  # nodeType
    name: str  # node name ("" for unnamed)


class AstError(Exception):
    """solc could not produce an AST for the source (parse failure)."""


def parse_ast(source: str) -> dict:
    """Run solc --ast-compact-json on the source; return the root AST node."""
    with tempfile.TemporaryDirectory(prefix="solast-") as tmp:
        path = Path(tmp) / "input.sol"
        path.write_text(source)
        proc = subprocess.run(
            ["solc", "--ast-compact-json", str(path)],
            capture_output=True,
            text=True,
            timeout=60,
        )
    out = proc.stdout
    # solc prints a banner ("JSON AST (compact format):\n\n======= file =======")
    marker = out.find("\n{")
    if proc.returncode != 0 or marker == -1:
        raise AstError(proc.stderr.strip() or "solc produced no AST")
    try:
        return json.loads(out[marker + 1 :])
    except json.JSONDecodeError as e:
        raise AstError(f"unparseable AST JSON: {e}") from e


def parses(source: str) -> bool:
    """Gate 1: solc --stop-after parsing (syntax only, ~ms, no node boot)."""
    with tempfile.TemporaryDirectory(prefix="solast-gate-") as tmp:
        path = Path(tmp) / "input.sol"
        path.write_text(source)
        proc = subprocess.run(
            ["solc", "--stop-after", "parsing", str(path)],
            capture_output=True,
            text=True,
            timeout=60,
        )
    return proc.returncode == 0


def _parse_src(src: str) -> tuple[int, int] | None:
    parts = src.split(":")
    if len(parts) != 3:
        return None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


def _walk(node, contract: str | None, in_function: bool, out: list[Span]):
    """Collect deletable spans. `contract`/`in_function` track context."""
    if isinstance(node, list):
        for item in node:
            _walk(item, contract, in_function, out)
        return
    if not isinstance(node, dict):
        return
    ntype = node.get("nodeType")
    if ntype == "ContractDefinition":
        contract = node.get("name", contract)
    if ntype == "FunctionDefinition":
        in_function = True
    parsed = _parse_src(node.get("src", ""))
    if parsed is not None:
        offset, length = parsed
        if ntype in _KIND_ORDER:
            if ntype == "FunctionDefinition":
                # constructors/fallback/receive are deployment-relevant; skip
                if node.get("kind") in _SKIP_FUNCTION_KINDS:
                    pass
                else:
                    out.append(Span(offset, length, ntype, node.get("name", "")))
            elif ntype == "VariableDeclaration":
                # state variables only (declared directly under a contract)
                if node.get("stateVariable"):
                    out.append(Span(offset, length, ntype, node.get("name", "")))
            else:
                out.append(Span(offset, length, ntype, node.get("name", "")))
        elif ntype in _STATEMENT_KINDS and in_function:
            out.append(Span(offset, length, ntype, ""))
    for key, value in node.items():
        if key in ("src",):
            continue
        _walk(value, contract, in_function, out)


def deletion_spans(
    source: str,
    *,
    keep_functions: set[str] | None = None,
) -> list[Span]:
    """Ordered deletion candidates for `source`.

    `keep_functions`: function names that surviving spec steps still call —
    their FunctionDefinitions are never proposed (the queue covers every
    contract in the file, not just the target).
    """
    keep = keep_functions or set()
    root = parse_ast(source)
    spans: list[Span] = []
    _walk(root, None, False, spans)
    # declaration spans exclude their terminating ';' — extend them so a
    # deletion doesn't leave a stray semicolon (which gate 1 would reject)
    data = source.encode("utf-8")
    adjusted: list[Span] = []
    for s in spans:
        if s.kind in ("VariableDeclaration", "EventDefinition", "ErrorDefinition"):
            end = s.offset + s.length
            if end < len(data) and data[end : end + 1] == b";":
                s = Span(s.offset, s.length + 1, s.kind, s.name)
        adjusted.append(s)
    spans = adjusted
    top = [
        s
        for s in spans
        if s.kind in _KIND_ORDER
        and not (s.kind == "FunctionDefinition" and s.name in keep)
    ]
    stmts = [s for s in spans if s.kind in _STATEMENT_KINDS]
    # a statement nested inside a proposed function is redundant until the
    # function deletion is rejected; keep both (re-parse happens on accept)
    top.sort(key=lambda s: (_KIND_ORDER[s.kind], -s.length))
    stmts.sort(key=lambda s: -s.length)
    return top + stmts


def splice(source: str, span: Span) -> str:
    """Textually delete the span (byte offsets on the UTF-8 encoding)."""
    data = bytearray(source.encode("utf-8"))
    if span.offset < 0 or span.offset + span.length > len(data):
        raise ValueError("span out of range")
    del data[span.offset : span.offset + span.length]
    return bytes(data).decode("utf-8")


# --- fallback: brace-aware line chunks (solc cannot parse the original) ------


def _depths(source: str) -> list[int]:
    """Brace depth after each line, skipping // and /* */ comments/strings."""
    depths: list[int] = []
    depth = 0
    in_block_comment = False
    for line in source.splitlines(keepends=True):
        i = 0
        in_str: str | None = None
        while i < len(line):
            c = line[i]
            two = line[i : i + 2]
            if in_block_comment:
                if two == "*/":
                    in_block_comment = False
                    i += 2
                    continue
                i += 1
                continue
            if in_str:
                if c == "\\":
                    i += 2
                    continue
                if c == in_str:
                    in_str = None
                i += 1
                continue
            if two == "//":
                break
            if two == "/*":
                in_block_comment = True
                i += 2
                continue
            if c in ('"', "'"):
                in_str = c
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
            i += 1
        depths.append(depth)
    return depths


def brace_chunks(source: str) -> list[str]:
    """Split source into contiguous line chunks at depth-stable boundaries.

    A chunk closes when the brace depth returns to its chunk-start depth and
    the line ends a syntactic item (';' or '}'). Concatenating all chunks
    reproduces the source exactly.
    """
    lines = source.splitlines(keepends=True)
    if not lines:
        return []
    depths = _depths(source)
    chunks: list[str] = []
    start = 0
    prev_depth = 0  # depth *before* the current chunk's first line
    for i, line in enumerate(lines):
        end_depth = depths[i]
        stripped = line.strip()
        closes_item = stripped.endswith(";") or stripped.endswith("}") or not stripped
        if i > start and end_depth == prev_depth and end_depth <= 1 and closes_item:
            chunks.append("".join(lines[start : i + 1]))
            start = i + 1
        prev_depth = end_depth
    if start < len(lines):
        chunks.append("".join(lines[start:]))
    return chunks
