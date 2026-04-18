// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.20;

contract Base {
    function compute(uint256 value) internal pure virtual returns (uint256) {
        return value + 1;
    }
}

contract Child is Base {
    // This override is useful for testing dispatch lowering in a small valid program.
    function compute(uint256 value) internal pure override returns (uint256) {
        return super.compute(value) * 2;
    }

    function probe(uint256 value) external pure returns (uint256) {
        return compute(value);
    }
}

