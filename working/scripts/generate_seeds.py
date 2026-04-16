#!/usr/bin/env python3

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shutil


@dataclass(frozen=True)
class SeedCase:
    name: str
    description: str
    source: str
    expectation: str = "shared-success"
    focus: str = "behavior"
    standalone_source: bool = False


def contract_name(name: str) -> str:
    return "".join(part.capitalize() for part in name.split("_"))


def render_case(case: SeedCase) -> str:
    if case.standalone_source:
        return f"""// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.20;

{case.source}
"""

    return f"""// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.20;

/// @title {contract_name(case.name)} differential seed
/// @notice {case.description}
contract {contract_name(case.name)} {{
{case.source}
}}
"""


def build_cases() -> list[SeedCase]:
    return [
        SeedCase(
            name="tuple_swap_storage",
            description="Checks tuple assignment when both sides reference storage-backed state.",
            source="""    uint256 public left;
    uint256 public right;

    // This case is meant to compile cleanly and later serve as a runtime seed.
    function probe(uint256 a, uint256 b) external {
        left = a;
        right = b;
        (left, right) = (right, left);
    }""",
        ),
        SeedCase(
            name="nested_tuple_destructure",
            description="Checks tuple destructuring through a small internal helper.",
            source="""    function pair(uint256 a, uint256 b) internal pure returns (uint256, uint256) {
        return (a + 1, b + 2);
    }

    // This seed checks tuple unpacking and multiple assignment in otherwise plain code.
    function probe(uint256 a, uint256 b) external pure returns (uint256, uint256) {
        (uint256 x, uint256 y) = pair(a, b);
        return (x, y);
    }""",
        ),
        SeedCase(
            name="short_circuit_assignment",
            description="Checks side effects inside a short-circuit boolean expression.",
            source="""    uint256 public counter;

    // This is a good runtime-oriented seed because the state transition is tiny.
    function probe(bool flag) external returns (uint256) {
        if (flag && ++counter > 0) {
            return counter;
        }

        return counter;
    }""",
        ),
        SeedCase(
            name="compound_assignment_order",
            description="Checks whether compilers agree on compound assignment ordering.",
            source="""    uint256 public total;

    // This case should compile on both compilers and is useful for runtime comparison.
    function probe(uint256 a, uint256 b) external returns (uint256) {
        total = a;
        total += b;
        return total;
    }""",
        ),
        SeedCase(
            name="constructor_state_dependency",
            description="Checks constructor writes that depend on earlier state initialization.",
            source="""    uint256 public a;
    uint256 public b;

    // Constructor state flow is a common source of behavioral drift.
    constructor(uint256 seed) {
        a = seed;
        b = a * 2;
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
            focus="abi",
        ),
        SeedCase(
            name="ternary_type_join",
            description="Checks ternary typing across nearby unsigned widths after explicit widening.",
            source="""    // Explicit widening avoids expected type errors while still exercising
    // how each compiler handles ternary join logic.
    function probe(bool cond, uint8 a, uint16 b) external pure returns (uint16) {
        return cond ? uint16(a) : b;
    }""",
        ),
        SeedCase(
            name="struct_roundtrip_memory",
            description="Checks returning a memory struct through a small helper pipeline.",
            source="""    struct Pair {
        uint256 left;
        uint256 right;
    }

    function build(uint256 a, uint256 b) internal pure returns (Pair memory) {
        return Pair({left: a + 1, right: b + 2});
    }

    // Returning a struct through an internal helper is a compact optimizer stress case.
    function probe(uint256 a, uint256 b) external pure returns (uint256, uint256) {
        Pair memory pair = build(a, b);
        return (pair.left, pair.right);
    }""",
        ),
        SeedCase(
            name="storage_array_push_pop",
            description="Checks a push/pop roundtrip on a dynamic storage array.",
            source="""    uint256[] public values;

    // Dynamic storage arrays are interesting because they exercise storage layout code.
    function probe(uint256 a, uint256 b) external returns (uint256) {
        values.push(a);
        values.push(b);
        values.pop();
        return values[values.length - 1];
    }""",
        ),
        SeedCase(
            name="fixed_array_assignment",
            description="Checks whole-value assignment of fixed-size memory arrays.",
            source="""    // Whole-array assignment stays valid while exercising aggregate copies.
    function probe(uint256 a, uint256 b) external pure returns (uint256, uint256) {
        uint256[2] memory first = [a, b];
        uint256[2] memory second = first;
        return (second[0], second[1]);
    }""",
        ),
        SeedCase(
            name="modifier_state_gate",
            description="Checks ordering between modifier code and function body state writes.",
            source="""    uint256 public seen;

    modifier bump(uint256 amount) {
        seen += amount;
        _;
    }

    // Modifier ordering bugs show up as runtime differences even in tiny programs.
    function probe(uint256 amount) external bump(amount) returns (uint256) {
        seen += 1;
        return seen;
    }""",
        ),
        SeedCase(
            name="inheritance_super_call",
            description="Checks override dispatch and super calls across a small inheritance chain.",
            source="""contract Base {
    function compute(uint256 value) internal pure virtual returns (uint256) {
        return value + 1;
    }
}

contract Child is Base {
    // This override is useful for testing dispatch lowering in a small valid program.
    function compute(uint256 value) internal pure override returns (uint256) {
        return super.compute(value) * 2;
    }

    function probe(uint256 value) external pure returns (uint256) {
        return compute(value);
    }
}
""",
            standalone_source=True,
        ),
        SeedCase(
            name="nested_loop_accumulator",
            description="Checks nested loop accumulation with a small bounded iteration space.",
            source="""    // Small nested loops are a cheap way to stress control-flow lowering.
    function probe(uint256 limit) external pure returns (uint256 sum) {
        for (uint256 i = 0; i < limit && i < 4; ++i) {
            for (uint256 j = 0; j < 3; ++j) {
                sum += i + j;
            }
        }
    }""",
        ),
        SeedCase(
            name="bytes_hash_roundtrip",
            description="Checks bytes allocation, writes, and hashing in a tiny pure function.",
            source="""    // Bytes manipulation hits memory layout logic without depending on ABI helpers.
    function probe(bytes calldata data) external pure returns (bytes32) {
        bytes memory copy = data;
        if (copy.length > 0) {
            copy[0] = bytes1(uint8(copy[0]) ^ 0x01);
        }

        return keccak256(copy);
    }""",
        ),
    ]


def main() -> None:
    root_dir = Path(__file__).resolve().parents[2]
    generated_dir = root_dir / "working" / "cases" / "generated"

    if generated_dir.exists():
        shutil.rmtree(generated_dir)

    generated_dir.mkdir(parents=True, exist_ok=True)

    cases = build_cases()
    manifest = []
    for case in cases:
        (generated_dir / f"{case.name}.sol").write_text(
            render_case(case), encoding="utf-8"
        )
        manifest.append(
            {
                "name": case.name,
                "expectation": case.expectation,
                "focus": case.focus,
                "description": case.description,
            }
        )

    (generated_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print(f"Generated {len(cases)} seed contracts in {generated_dir}")


if __name__ == "__main__":
    main()
