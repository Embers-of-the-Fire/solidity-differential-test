// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.20;

contract TryCatchInitializer {
    uint256 public value = seed();

    function seed() internal returns (uint256) {
        try this.ext() returns (uint256 x) {
            return x;
        } catch {
            return 7;
        }
    }

    function ext() external pure returns (uint256) {
        return 5;
    }
}
