// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

interface IStatefulCounter {
    function increment(uint256 by) external payable;

    function get() external view returns (uint256);
}

contract CallerProxy {
    event Forwarded(address indexed target, uint256 by, uint256 valueSent);

    function forwardIncrement(address target, uint256 by) external payable {
        IStatefulCounter(target).increment{value: msg.value}(by);
        emit Forwarded(target, by, msg.value);
    }

    function readCounter(address target) external view returns (uint256) {
        return IStatefulCounter(target).get();
    }
}
