// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.20;

/// @title TernaryTypeJoin differential seed
/// @notice Checks ternary typing across nearby unsigned widths after explicit widening.
contract TernaryTypeJoin {
    // Explicit widening avoids expected type errors while still exercising
    // how each compiler handles ternary join logic.
    function probe(bool cond, uint8 a, uint16 b) external pure returns (uint16) {
        return cond ? uint16(a) : b;
    }
}
