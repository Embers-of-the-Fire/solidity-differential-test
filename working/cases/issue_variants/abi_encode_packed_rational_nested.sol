// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.20;

/// @title Variant of Solang issue #1864
/// @notice This uses a rational expression nested inside parentheses for abi.encodePacked.
contract AbiEncodePackedRationalNested {
    function probe() external pure returns (bytes memory) {
        // The nested form checks whether the same rational-type bug survives a
        // slightly different expression shape.
        return abi.encodePacked((1 - 24.24));
    }
}
