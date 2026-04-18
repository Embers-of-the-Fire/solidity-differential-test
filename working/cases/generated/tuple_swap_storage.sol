// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.20;

/// @title TupleSwapStorage differential seed
/// @notice Checks tuple assignment when both sides reference storage-backed state.
contract TupleSwapStorage {
    uint256 public left;
    uint256 public right;

    // This case is meant to compile cleanly and later serve as a runtime seed.
    function probe(uint256 a, uint256 b) external {
        left = a;
        right = b;
        (left, right) = (right, left);
    }
}
