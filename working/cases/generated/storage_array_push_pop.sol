// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.20;

/// @title StorageArrayPushPop differential seed
/// @notice Checks a push/pop roundtrip on a dynamic storage array.
contract StorageArrayPushPop {
    uint256[] public values;

    // Dynamic storage arrays are interesting because they exercise storage layout code.
    function probe(uint256 a, uint256 b) external returns (uint256) {
        values.push(a);
        values.push(b);
        values.pop();
        return values[values.length - 1];
    }
}
