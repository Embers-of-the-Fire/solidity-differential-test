from __future__ import annotations

from dataclasses import dataclass

from eth_utils import keccak


@dataclass(slots=True)
class IoOracleCase:
    contract_name: str
    source: str
    calldata_evm: str
    calldata_solang_polkadot: str
    expect_evm: str
    expect_solang_polkadot: str
    expected_value: int


def make_uint256_io_oracle(
    contract_name: str,
    expression: str,
    input_value: int,
) -> IoOracleCase:
    output = _eval_uint256_expression(expression, input_value)
    source = f"""// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.20;

contract {contract_name} {{
    function run(uint256 a) external pure returns (uint256) {{
        return {expression};
    }}
}}
"""
    selector = function_selector("run(uint256)")
    encoded_input = encode_uint256(input_value)
    return IoOracleCase(
        contract_name=contract_name,
        source=source,
        calldata_evm=selector + encoded_input.removeprefix("0x"),
        calldata_solang_polkadot=selector
        + encode_uint256_little(input_value).removeprefix("0x"),
        expect_evm=encode_uint256(output),
        expect_solang_polkadot=encode_uint256_little(output),
        expected_value=output,
    )


def function_selector(signature: str) -> str:
    return "0x" + keccak(text=signature)[:4].hex()


def encode_uint256(value: int) -> str:
    if value < 0 or value >= 2**256:
        msg = "uint256 value is out of range"
        raise ValueError(msg)
    return "0x" + value.to_bytes(32, "big").hex()


def encode_uint256_little(value: int) -> str:
    if value < 0 or value >= 2**256:
        msg = "uint256 value is out of range"
        raise ValueError(msg)
    return "0x" + value.to_bytes(32, "little").hex()


def decode_uint256(value: str) -> int:
    data = bytes.fromhex(value.removeprefix("0x"))
    if len(data) != 32:
        msg = "uint256 return must be exactly 32 bytes"
        raise ValueError(msg)
    return int.from_bytes(data, "big")


def decode_uint256_little(value: str) -> int:
    data = bytes.fromhex(value.removeprefix("0x"))
    if len(data) != 32:
        msg = "uint256 return must be exactly 32 bytes"
        raise ValueError(msg)
    return int.from_bytes(data, "little")


def _eval_uint256_expression(expression: str, input_value: int) -> int:
    allowed_globals = {"__builtins__": {}}
    allowed_locals = {"a": input_value}
    python_expression = expression.replace("&&", " and ").replace("||", " or ")
    value = eval(python_expression, allowed_globals, allowed_locals)  # noqa: S307
    if not isinstance(value, int):
        msg = "expression must evaluate to an integer"
        raise ValueError(msg)
    return value % (2**256)
