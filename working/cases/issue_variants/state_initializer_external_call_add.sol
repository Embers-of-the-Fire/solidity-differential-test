// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.20;

/// @title Variant of Solang issue #1869
/// @notice This wraps the external call in a larger initializer expression.
contract StateInitializerExternalCallAdd {
    // This should either be rejected cleanly or resolved without crashing sema.
    uint256 public value = this.seed() + 1;

    function seed() external pure returns (uint256) {
        return 2;
    }
}
