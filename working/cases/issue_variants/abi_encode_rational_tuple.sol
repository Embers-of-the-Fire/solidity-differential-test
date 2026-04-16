// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.20;

/// @title Variant of Solang issue #1864
/// @notice This embeds a rational expression alongside a normal scalar in abi.encode.
contract AbiEncodeRationalTuple {
    function probe() external pure returns (bytes memory) {
        // This should be diagnosed cleanly if rationals are unsupported here.
        return abi.encode(1 - 24.24, uint8(5));
    }
}
