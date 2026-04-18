// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.20;

/// @title ShortCircuitAssignment differential seed
/// @notice Checks side effects inside a short-circuit boolean expression.
contract ShortCircuitAssignment {
    uint256 public counter;

    // This is a good runtime-oriented seed because the state transition is tiny.
    function probe(bool flag) external returns (uint256) {
        if (flag && ++counter > 0) {
            return counter;
        }

        return counter;
    }
}
