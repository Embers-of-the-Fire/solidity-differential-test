#!/usr/bin/env python3

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class VariantCase:
    path: Path
    target: str
    issue: str
    note: str


def build_cases(root_dir: Path) -> list[VariantCase]:
    base = root_dir / "working" / "cases" / "issue_variants"
    return [
        VariantCase(
            path=base / "abi_encode_internal_fn_var.sol",
            target="evm",
            issue="#1862",
            note="local internal function variable passed to abi.encode",
        ),
        VariantCase(
            path=base / "abi_encode_internal_fn_packed_tuple.sol",
            target="evm",
            issue="#1862",
            note=(
                "internal function reference used as one variadic "
                "abi.encodePacked argument"
            ),
        ),
        VariantCase(
            path=base / "abi_encode_rational_tuple.sol",
            target="evm",
            issue="#1864",
            note="rational expression embedded alongside a scalar in abi.encode",
        ),
        VariantCase(
            path=base / "abi_encode_packed_rational_nested.sol",
            target="evm",
            issue="#1864",
            note="parenthesized rational expression passed to abi.encodePacked",
        ),
        VariantCase(
            path=base / "state_initializer_external_call_add.sol",
            target="solana",
            issue="#1869",
            note="external call wrapped in an arithmetic initializer",
        ),
        VariantCase(
            path=base / "state_initializer_external_call_conditional.sol",
            target="solana",
            issue="#1869",
            note="external call hidden behind a conditional initializer",
        ),
    ]


def classify(stderr: str, exit_code: int) -> str:
    lowered = stderr.lower()
    if (
        "internal error" in lowered
        or "panicked at" in lowered
        or "thread 'main' panicked" in lowered
    ):
        return "panic"
    if exit_code == 0:
        return "success"
    return "diagnostic"


def main() -> None:
    root_dir = Path(__file__).resolve().parents[2]
    cases = build_cases(root_dir)

    for case in cases:
        result = subprocess.run(
            ["solang", "compile", "--target", case.target, str(case.path)],
            capture_output=True,
            text=True,
        )
        kind = classify(result.stderr, result.returncode)

        print(f"{case.path.name}: {kind}: {case.issue}: {case.note}")
        if kind != "success":
            for line in result.stderr.strip().splitlines()[:4]:
                print(f"  {line}")


if __name__ == "__main__":
    main()
