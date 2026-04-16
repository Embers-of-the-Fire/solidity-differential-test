#!/usr/bin/env python3

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil


@dataclass(frozen=True)
class SeedCase:
    name: str
    description: str
    source: str


def contract_name(name: str) -> str:
    return "".join(part.capitalize() for part in name.split("_"))


def render_case(case: SeedCase) -> str:
    return f"""// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.20;

/// @title {contract_name(case.name)} differential seed
/// @notice {case.description}
contract {contract_name(case.name)} {{
{case.source}
}}
"""


def build_cases() -> list[SeedCase]:
    cases: list[SeedCase] = []

    integer_types = ["uint8", "uint16", "uint256", "int8"]
    literal_values = ["0", "1", "255", "256", "-1"]

    for integer_type in integer_types:
        for literal in literal_values:
            cases.append(
                SeedCase(
                    name=f"literal_cast_{integer_type}_{literal.replace('-', 'neg')}",
                    description=(
                        "Checks how each compiler handles explicit casts from integer literals "
                        f"into {integer_type}."
                    ),
                    source=f"""    // This seed isolates explicit integer literal casts.
    function probe() external pure returns ({integer_type}) {{
        return {integer_type}({literal});
    }}""",
                )
            )

    for visibility in ["external", "public"]:
        for data_location in ["memory", "calldata"]:
            if visibility == "public" and data_location == "calldata":
                continue

            cases.append(
                SeedCase(
                    name=f"string_location_{visibility}_{data_location}",
                    description=(
                        "Checks whether string parameter data locations are accepted and typed "
                        "consistently."
                    ),
                    source=f"""    // This seed focuses on parameter data locations for dynamic types.
    function probe(string {data_location} value) {visibility} pure returns (bytes32) {{
        return keccak256(bytes(value));
    }}""",
                )
            )

    for return_location in ["memory", "calldata"]:
        cases.append(
            SeedCase(
                name=f"array_return_{return_location}",
                description="Checks dynamic array return data locations in simple pure functions.",
                source=f"""    // This seed checks return-location handling for dynamic arrays.
    function probe(uint256[] {return_location} input) external pure returns (uint256[] {return_location}) {{
        return input;
    }}""",
            )
        )

    cases.extend(
        [
            SeedCase(
                name="tuple_swap_storage",
                description="Checks tuple assignment when both sides reference storage-backed state.",
                source="""    uint256 public left;
    uint256 public right;

    // This seed checks tuple assignment ordering and storage writes.
    function probe(uint256 a, uint256 b) external {
        left = a;
        right = b;
        (left, right) = (right, left);
    }""",
            ),
            SeedCase(
                name="custom_error_branch",
                description="Checks custom error declarations and revert sites in a tiny branch.",
                source="""    error TooSmall(uint256 observed);

    // This seed checks whether custom errors are parsed and lowered consistently.
    function probe(uint256 value) external pure returns (uint256) {
        if (value < 3) {
            revert TooSmall(value);
        }

        return value;
    }""",
            ),
            SeedCase(
                name="public_mapping_getter",
                description="Checks synthesized getters for public mappings with scalar values.",
                source="""    // This public mapping is useful because compilers synthesize a getter for it.
    mapping(uint256 => uint256) public values;

    function probe(uint256 key, uint256 value) external {
        values[key] = value;
    }""",
            ),
            SeedCase(
                name="constructor_state_dependency",
                description="Checks constructor writes that depend on earlier state initialization.",
                source="""    uint256 public a;
    uint256 public b;

    // This seed checks whether constructor assignment order is preserved.
    constructor(uint256 seed) {
        a = seed;
        b = a * 2;
    }""",
            ),
            SeedCase(
                name="fallback_receive_pair",
                description="Checks coexistence of receive and fallback entry points.",
                source="""    uint256 public hits;

    // This seed checks whether both special functions are accepted together.
    receive() external payable {
        hits += 1;
    }

    fallback() external payable {
        hits += 10;
    }""",
            ),
        ]
    )

    return cases


def main() -> None:
    root_dir = Path(__file__).resolve().parents[2]
    generated_dir = root_dir / "working" / "cases" / "generated"

    if generated_dir.exists():
        shutil.rmtree(generated_dir)

    generated_dir.mkdir(parents=True, exist_ok=True)

    cases = build_cases()
    for case in cases:
        (generated_dir / f"{case.name}.sol").write_text(
            render_case(case), encoding="utf-8"
        )

    print(f"Generated {len(cases)} seed contracts in {generated_dir}")


if __name__ == "__main__":
    main()
