// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.20;

contract RationalEncode {
    function probe() external pure returns (bytes memory) {
        return abi.encode(1 - 0.125, uint8(2));
    }
}
