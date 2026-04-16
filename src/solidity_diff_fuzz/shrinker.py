from __future__ import annotations


def trim_trailing_blank_lines(source: str) -> str:
    return source.rstrip() + "\n"
