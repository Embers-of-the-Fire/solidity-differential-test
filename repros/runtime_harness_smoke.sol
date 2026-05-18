// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.20;

// This file is for validating the runtime harness itself, not Solang.
// `runtime-smoke` compiles it with solc, extracts creation bytecode from
// `solc --bin`, and deploys it with Geth's `evm run --create`.
contract RuntimeHarnessSmoke {
    function answer() external pure returns (uint256) {
        return 42;
    }
}
