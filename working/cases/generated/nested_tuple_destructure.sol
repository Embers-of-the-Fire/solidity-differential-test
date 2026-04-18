// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.20;

/// @title NestedTupleDestructure differential seed
/// @notice Checks tuple destructuring through a small internal helper.
contract NestedTupleDestructure {
    function pair(uint256 a, uint256 b) internal pure returns (uint256, uint256) {
        return (a + 1, b + 2);
    }

    // This seed checks tuple unpacking and multiple assignment in otherwise plain code.
    function probe(uint256 a, uint256 b) external pure returns (uint256, uint256) {
        (uint256 x, uint256 y) = pair(a, b);
        return (x, y);
    }
}
