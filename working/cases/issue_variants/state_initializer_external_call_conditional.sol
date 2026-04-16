// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.20;

/// @title Variant of Solang issue #1869
/// @notice This puts the external call behind a conditional operator in the initializer.
contract StateInitializerExternalCallConditional {
    // This should be handled by semantic analysis rather than unwrapping missing context.
    uint256 public value = true ? this.seed() : 0;

    function seed() external pure returns (uint256) {
        return 3;
    }
}
