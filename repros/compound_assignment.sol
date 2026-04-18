// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.20;

contract CompoundAssignment {
    uint8 public value;

    function probe(uint8 a, uint8 b) external returns (uint8) {
        value = a;
        value += b;
        return value;
    }
}
