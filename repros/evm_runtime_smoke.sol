// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.20;

// Minimal smoke input for the runtime comparison harness.
// solc emits EVM bytecode, but pinned Solang 0.3.4 cannot emit EVM bytecode and
// panics with "target not implemented" before runtime comparison can execute.
contract EvmRuntimeSmoke {
    uint256 public total;

    constructor(uint256 seed) {
        total = seed + 1;
    }

    function add(uint256 value) external returns (uint256) {
        total += value;
        return total;
    }

    function pair(uint256 left, uint256 right)
        external
        pure
        returns (uint256, uint256)
    {
        return (right + 1, left + 2);
    }
}
