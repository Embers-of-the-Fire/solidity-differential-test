// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.20;

/// @title FixedArrayAssignment differential seed
/// @notice Checks whole-value assignment of fixed-size memory arrays.
contract FixedArrayAssignment {
    // Whole-array assignment stays valid while exercising aggregate copies.
    function probe(uint256 a, uint256 b) external pure returns (uint256, uint256) {
        uint256[2] memory first = [a, b];
        uint256[2] memory second = first;
        return (second[0], second[1]);
    }
}
