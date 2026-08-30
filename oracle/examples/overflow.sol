contract overflow {
    uint8 public x;

    constructor(uint8 init) {
        x = init;
    }

    // checked arithmetic: solc reverts with Panic(0x11);
    // solang's revert payload differs -> the oracle should flag it
    function bump() public returns (uint8) {
        x += 200;
        return x;
    }
}
