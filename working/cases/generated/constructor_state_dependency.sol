// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.20;

/// @title ConstructorStateDependency differential seed
/// @notice Checks constructor writes that depend on earlier state initialization.
contract ConstructorStateDependency {
    uint256 public a;
    uint256 public b;

    // Constructor state flow is a common source of behavioral drift.
    constructor(uint256 seed) {
        a = seed;
        b = a * 2;
    }
}
