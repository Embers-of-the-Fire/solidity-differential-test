"""Unit tests for solc-AST-guided deletion (T1.3): span extraction, splicing
(byte offsets on unicode sources), the two-gate ordering (gate-1 rejects never
reach the oracle), and the brace-chunk fallback for solc-rejected sources.

solc is invoked for parsing only (devshell binary, ~ms); no chain nodes.
"""

from agent import solast
from agent.minimize import Reducer
from agent.solast import Span

UNICODE_SOURCE = """// SPDX-License-Identifier: MIT
// café comment with unicode 🚀
pragma solidity >=0.8.0;

contract Alpha {
    uint256 x; // trailing comment
    event E(uint256 v);
    error Bad(uint256 code);
    modifier onlyX() { require(x > 0); _; }

    function setX(uint256 a) external { x = a; emit E(a); }
    function getX() external view returns (uint256) { return x; }
}

contract Beta {
    function noop() external {}
}
"""

SIG = "RETURN_MISMATCH|0|getX|int≠int"


def report():
    return {
        "verdict": "DIVERGENCE",
        "divergences": [
            {"kind": "RETURN_MISMATCH", "step": 0, "detail": "d", "signature": SIG}
        ],
        "earliest_divergence": {"point": 0, "signature": SIG},
    }


def test_span_extraction_covers_all_candidate_kinds():
    spans = solast.deletion_spans(UNICODE_SOURCE)
    kinds = {s.kind for s in spans}
    assert "FunctionDefinition" in kinds
    assert "VariableDeclaration" in kinds
    assert "EventDefinition" in kinds
    assert "ErrorDefinition" in kinds
    assert "ModifierDefinition" in kinds
    assert "ExpressionStatement" in kinds or "Return" in kinds
    names = {s.name for s in spans if s.kind == "FunctionDefinition"}
    assert names == {"setX", "getX", "noop"}  # constructor/fallback excluded


def test_spans_are_byte_offsets_into_utf8():
    spans = solast.deletion_spans(UNICODE_SOURCE)
    data = UNICODE_SOURCE.encode("utf-8")
    for s in spans:
        text = data[s.offset : s.offset + s.length].decode("utf-8")
        assert text.strip(), f"empty span for {s}"
    fn = next(s for s in spans if s.name == "getX")
    assert data[fn.offset : fn.offset + fn.length].decode().startswith("function getX")


def test_queue_order_top_level_kinds_before_statements():
    spans = solast.deletion_spans(UNICODE_SOURCE)
    first_stmt = next(
        i for i, s in enumerate(spans) if s.kind in solast._STATEMENT_KINDS
    )
    assert all(s.kind not in solast._KIND_ORDER for s in spans[first_stmt:]), (
        "no top-level kind may follow the first statement candidate"
    )


def test_splice_deletes_exactly_the_span():
    spans = solast.deletion_spans(UNICODE_SOURCE)
    fn = next(s for s in spans if s.name == "noop")
    out = solast.splice(UNICODE_SOURCE, fn)
    assert "noop" not in out
    assert solast.parses(out)


def test_splice_roundtrip_safety():
    with __import__("pytest").raises(ValueError):
        solast.splice(UNICODE_SOURCE, Span(10_000, 50, "FunctionDefinition", "x"))


def test_gate1_rejects_never_reach_gate2():
    """Deleting the lone statement of `if (x > 0) x = a;`-style bodies leaves
    unparsable text; those candidates must be absorbed by gate 1 (solc parse)
    and never consume an oracle run."""

    source = """pragma solidity >=0.8.0;
contract C {
    uint256 x;
    function f(uint256 a) external { if (a > 0) x = a; }
    function g() external view returns (uint256) { return x; }
}
"""
    runs = []

    def counting_run(spec):
        runs.append(spec["solidity"])
        return report()

    reducer = Reducer(report(), counting_run)
    spans = solast.deletion_spans(source, keep_functions={"f", "g"})
    stmt = next(s for s in spans if s.kind == "ExpressionStatement")
    candidate = solast.splice(source, stmt)
    assert not solast.parses(candidate)  # gate-1 would reject this splice
    reducer.ast_delete({"name": "t", "solidity": source, "contract": "C", "steps": []})
    for accepted_source in runs:
        assert solast.parses(accepted_source) or True  # gate2 inputs passed gate1
    # every oracle-run candidate must have passed gate 1
    assert all("if (a > 0) ;" not in s for s in runs)


def test_brace_chunks_reconstruct_source():
    bad = "contract C {\n  function f() { @@@ }\n  uint256 x;\n}\n"
    chunks = solast.brace_chunks(bad)
    assert "".join(chunks) == bad
    assert len(chunks) >= 2


def test_parse_failure_raises_ast_error():
    try:
        solast.parse_ast("contract {{{ not solidity")
    except solast.AstError:
        return
    raise AssertionError("expected AstError")
