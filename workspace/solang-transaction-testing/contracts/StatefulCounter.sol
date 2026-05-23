// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract StatefulCounter {
    uint256 private value;
    address public lastCaller;
    uint256 public lastValue;

    event Incremented(address indexed caller, uint256 by, uint256 newValue);

    constructor(uint256 initialValue) payable {
        value = initialValue;
        lastCaller = msg.sender;
        lastValue = msg.value;
    }

    function increment(uint256 by) external payable {
        require(by != 0, "zero increment");
        value += by;
        lastCaller = msg.sender;
        lastValue = msg.value;
        emit Incremented(msg.sender, by, value);
    }

    function get() external view returns (uint256) {
        return value;
    }
}
