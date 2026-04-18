// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.20;

contract TupleStructStorageSwap {
    struct PairTuple {
        uint256[2] items;
        uint256 total;
    }

    PairTuple public slot;

    function probe(uint256 a, uint256 b, uint256 c)
        external
        returns (uint256, uint256, uint256)
    {
        uint256[2] memory items = [a, b];
        slot = PairTuple({items: items, total: c});
        (slot.items[0], slot.items[1]) = (slot.items[1], slot.items[0] + c);
        return (slot.items[0], slot.items[1], slot.total);
    }
}
