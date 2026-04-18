// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.20;

/// @title PublicMappingGetter differential seed
/// @notice Checks synthesized getters for public mappings with scalar values.
contract PublicMappingGetter {
    // This public mapping is useful because compilers synthesize a getter for it.
    mapping(uint256 => uint256) public values;

    function probe(uint256 key, uint256 value) external {
        values[key] = value;
    }
}
