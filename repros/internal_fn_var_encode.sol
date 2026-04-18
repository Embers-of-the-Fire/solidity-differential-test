// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.20;

contract InternalFnVarEncode {
    function helper() internal pure returns (uint256) {
        return 7;
    }

    function probe() external pure returns (bytes memory) {
        function() internal pure returns (uint256) fn = helper;
        return abi.encode(fn);
    }
}
