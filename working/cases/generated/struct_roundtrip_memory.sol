// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.20;

/// @title StructRoundtripMemory differential seed
/// @notice Checks returning a memory struct through a small helper pipeline.
contract StructRoundtripMemory {
    struct Pair {
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
    }
}
