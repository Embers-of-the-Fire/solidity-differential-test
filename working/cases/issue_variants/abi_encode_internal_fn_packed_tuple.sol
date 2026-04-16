// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.20;

/// @title Variant of Solang issue #1862
/// @notice This passes an internal function reference alongside a scalar argument.
contract AbiEncodeInternalFnPackedTuple {
    function helper(uint256 value) internal pure returns (uint256) {
        return value + 1;
    }

    function probe() external pure returns (bytes memory) {
        // This variant checks whether the panic also appears when the internal
        // function is only one element of a variadic abi-encode call.
        return abi.encodePacked(helper, uint8(3));
    }
}
