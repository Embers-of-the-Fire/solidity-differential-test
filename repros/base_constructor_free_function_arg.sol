// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.20;

function seed(uint256 x) pure returns (uint256) {
    return x + 1;
}

contract BaseConstructorArg {
    constructor(uint256 x) {}
}

contract BaseConstructorArgChild is BaseConstructorArg(seed(1)) {}
