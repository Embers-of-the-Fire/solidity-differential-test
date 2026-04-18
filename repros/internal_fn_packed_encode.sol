// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.20;

contract InternalFnPackedEncode {
    function helper(uint256 value) internal pure returns (uint256) {
        return value + 1;
    }

    function probe() external pure returns (bytes memory) {
        return abi.encodePacked(helper, uint8(3));
    }
}
