// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.20;

contract ComplexStructArrayCompoundAssignment {
    struct Packet {
        uint8[2] items;
        uint8 total;
    }

    Packet public packet;

    function probe(uint8 a, uint8 b, uint8 c) external returns (uint8, uint8, uint8) {
        uint8[2] memory items = [a, b];
        Packet memory first = Packet({items: items, total: c});
        Packet memory second = first;
        packet = second;
        packet.items[0] += c;
        return (packet.items[0], packet.items[1], packet.total);
    }
}
