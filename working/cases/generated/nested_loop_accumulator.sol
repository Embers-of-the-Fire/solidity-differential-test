// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.20;

/// @title NestedLoopAccumulator differential seed
/// @notice Checks nested loop accumulation with a small bounded iteration space.
contract NestedLoopAccumulator {
    // Small nested loops are a cheap way to stress control-flow lowering.
    function probe(uint256 limit) external pure returns (uint256 sum) {
        for (uint256 i = 0; i < limit && i < 4; ++i) {
            for (uint256 j = 0; j < 3; ++j) {
                sum += i + j;
            }
        }
    }
}
