contract counter {
    event Changed(int64 indexed by, int64 value);

    int64 public count;

    constructor(int64 init) {
        count = init;
    }

    function inc(int64 by) public returns (int64) {
        count += by;
        emit Changed(by, count);
        return count;
    }

    function dec(int64 by) public returns (int64) {
        count -= by;
        emit Changed(-by, count);
        return count;
    }

    function fail() public {
        revert("boom");
    }
}
