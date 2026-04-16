// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.20;

/// @title Constructor ordering probe for compiler differential testing
/// @notice This case is useful for checking initialization semantics at compile time
/// and later as a runtime seed once an execution harness is added.
contract ConstructorOrder {
    uint256 public a;
    uint256 public b;

    constructor(uint256 seed) {
        // The order here is intentional. If a compiler mishandles constructor
        // execution or storage writes, this becomes a good runtime seed case.
        a = seed;
        b = a + 1;
    }
}
