// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.20;

/// @title CompoundAssignmentOrder differential seed
/// @notice Checks whether compilers agree on compound assignment ordering.
contract CompoundAssignmentOrder {
    uint256 public total;

    // This case should compile on both compilers and is useful for runtime comparison.
    function probe(uint256 a, uint256 b) external returns (uint256) {
        total = a;
        total += b;
        return total;
    }
}
