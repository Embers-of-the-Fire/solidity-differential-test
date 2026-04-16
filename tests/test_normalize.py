from __future__ import annotations

from solidity_diff_fuzz.normalize import classify_outcome, normalize_text


def test_classify_parser_diagnostic() -> None:
    outcome, diagnostic = classify_outcome(1, "ParserError: expected ';'")
    assert outcome.value == "diagnostic"
    assert diagnostic.value == "parser"


def test_normalize_text_strips_ansi_and_whitespace() -> None:
    raw = "\x1b[31merror\x1b[0m  \nnext line   \n"
    assert normalize_text(raw) == "error\nnext line"
