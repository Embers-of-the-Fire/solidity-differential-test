// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.20;

/// @title BytesHashRoundtrip differential seed
/// @notice Checks bytes allocation, writes, and hashing in a tiny pure function.
contract BytesHashRoundtrip {
    // Bytes manipulation hits memory layout logic without depending on ABI helpers.
    function probe(bytes calldata data) external pure returns (bytes32) {
        bytes memory copy = data;
        if (copy.length > 0) {
            copy[0] = bytes1(uint8(copy[0]) ^ 0x01);
        }

        return keccak256(copy);
    }
}
