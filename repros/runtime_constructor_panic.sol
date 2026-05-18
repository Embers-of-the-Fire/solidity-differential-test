// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.20;

// Runtime failure smoke for the EVM harness.
// This compiles with solc, but deployment executes a Solidity assert and should
// fail at runtime rather than during compilation.
contract RuntimeConstructorPanic {
    constructor() {
        assert(false);
    }
}
