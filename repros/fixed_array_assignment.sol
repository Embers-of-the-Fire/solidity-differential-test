// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.20;

contract FixedArrayAssignment {
    function probe(uint8 a, uint8 b) external pure returns (uint8, uint8) {
        uint8[2] memory first = [a, b];
        uint8[2] memory second = first;
        return (second[0], second[1]);
    }
}
