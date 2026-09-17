from agent.generator import validate_spec_dict

VALID_SOURCE = """// SPDX-License-Identifier: MIT
pragma solidity >=0.8.0;
contract c {
    int64 public count;
    constructor(int64 start) { count = start; }
    function inc(int64 d) public { count += d; }
}
"""


def valid_spec():
    return {
        "name": "t",
        "solidity": VALID_SOURCE,
        "contract": "c",
        "constructor": {"args": [1]},
        "oracle": {
            "storage": "count",
            "events": True,
            "revert_reasons": True,
            "gas": False,
        },
        "steps": [
            {"action": "call", "function": "inc", "args": [5], "sender": "alice"},
            {"action": "query", "function": "count"},
        ],
    }


def test_valid_spec_passes():
    assert validate_spec_dict(valid_spec()) == []


def test_missing_source():
    spec = valid_spec()
    del spec["solidity"]
    assert any("solidity" in p for p in validate_spec_dict(spec))


def test_source_file_rejected():
    spec = valid_spec()
    del spec["solidity"]
    spec["source_file"] = "c.sol"
    assert any("source_file" in p for p in validate_spec_dict(spec))


def test_struct_args_rejected():
    spec = valid_spec()
    spec["steps"][0]["args"] = [{"x": 1}]
    assert any("args" in p for p in validate_spec_dict(spec))


def test_bad_sender_rejected():
    spec = valid_spec()
    spec["steps"][0]["sender"] = "mallory"
    assert any("sender" in p for p in validate_spec_dict(spec))


def test_undeclared_function_rejected():
    spec = valid_spec()
    spec["steps"][1]["function"] = "dec"
    assert any("not declared" in p for p in validate_spec_dict(spec))


def test_wrong_contract_name_rejected():
    spec = valid_spec()
    spec["contract"] = "other"
    assert any("not declared" in p for p in validate_spec_dict(spec))


def test_too_many_steps_rejected():
    spec = valid_spec()
    spec["steps"] = spec["steps"] * 5
    assert any("too many steps" in p for p in validate_spec_dict(spec))


def test_gas_must_stay_off():
    spec = valid_spec()
    spec["oracle"]["gas"] = True
    assert any("gas" in p for p in validate_spec_dict(spec))


def test_label_args_and_value_ok():
    spec = valid_spec()
    spec["steps"][0]["args"] = ["$alice", ["$bob", 3], "0xdeadbeef"]
    spec["steps"][0]["value"] = 10**15
    assert validate_spec_dict(spec) == []
