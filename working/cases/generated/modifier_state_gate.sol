// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.20;

/// @title ModifierStateGate differential seed
/// @notice Checks ordering between modifier code and function body state writes.
contract ModifierStateGate {
    uint256 public seen;

    modifier bump(uint256 amount) {
        seen += amount;
        _;
    }

    // Modifier ordering bugs show up as runtime differences even in tiny programs.
    function probe(uint256 amount) external bump(amount) returns (uint256) {
        seen += 1;
        return seen;
    }
}
