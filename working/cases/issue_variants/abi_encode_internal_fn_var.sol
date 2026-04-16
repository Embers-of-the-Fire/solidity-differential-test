// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.20;

/// @title Variant of Solang issue #1862
/// @notice This stores an internal function in a local variable before abi-encoding it.
contract AbiEncodeInternalFnVar {
    function helper() internal pure returns (uint256) {
        return 7;
    }

    function probe() external pure returns (bytes memory) {
        function() internal pure returns (uint256) fn = helper;

        // This should be rejected with a clean diagnostic if internal function
        // references are not encodable.
        return abi.encode(fn);
    }
}
