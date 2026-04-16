// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.20;

/// @title Minimal storage contract for compiler differential testing
/// @notice This case intentionally stays simple so output differences are easier to inspect.
contract MinimalStorage {
    // This state variable is used to check whether both compilers accept
    // the same storage declaration and generate equivalent compile artifacts.
    uint256 public value;

    /// @notice Stores a caller-provided value.
    /// @param newValue The value to persist in contract storage.
    function set(uint256 newValue) external {
        value = newValue;
    }

    /// @notice Returns the current stored value.
    function get() external view returns (uint256) {
        return value;
    }
}
