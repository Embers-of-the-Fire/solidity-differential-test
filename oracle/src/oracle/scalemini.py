"""Minimal SCALE codec helpers for ContractsApi runtime calls.

Only what the oracle needs: encoding the `ContractsApi.call` parameter tuple and
decoding the `ContractExecResult` response, without relying on substrate-interface
type-registry details (its `ContractCallFlags` registry is stale and lacks the
REVERT bit).
"""

from __future__ import annotations


def compact_encode(n: int) -> bytes:
    if n < 0:
        raise ValueError("compact cannot encode negative values")
    if n < 1 << 6:
        return bytes([n << 2])
    if n < 1 << 14:
        return ((n << 2) | 0x01).to_bytes(2, "little")
    if n < 1 << 30:
        return ((n << 2) | 0x02).to_bytes(4, "little")
    raw = n.to_bytes((n.bit_length() + 7) // 8, "little")
    return bytes([((len(raw) - 4) << 2) | 0x03]) + raw


def compact_decode(data: bytes, off: int = 0) -> tuple[int, int]:
    mode = data[off] & 0x03
    if mode == 0:
        return data[off] >> 2, off + 1
    if mode == 1:
        return int.from_bytes(data[off : off + 2], "little") >> 2, off + 2
    if mode == 2:
        return int.from_bytes(data[off : off + 4], "little") >> 2, off + 4
    nbytes = (data[off] >> 2) + 4
    return int.from_bytes(data[off + 1 : off + 1 + nbytes], "little"), off + 1 + nbytes


def scale_bytes(data: bytes) -> bytes:
    return compact_encode(len(data)) + data


def u64(n: int) -> bytes:
    return n.to_bytes(8, "little")


def u128(n: int) -> bytes:
    return n.to_bytes(16, "little")


class Decoder:
    """Cursor-based decoder over raw SCALE bytes."""

    def __init__(self, data: bytes):
        self.data = data
        self.off = 0

    def take(self, n: int) -> bytes:
        chunk = self.data[self.off : self.off + n]
        if len(chunk) != n:
            raise ValueError("unexpected end of SCALE data")
        self.off += n
        return chunk

    def u8(self) -> int:
        return self.take(1)[0]

    def u32(self) -> int:
        return int.from_bytes(self.take(4), "little")

    def u64(self) -> int:
        return int.from_bytes(self.take(8), "little")

    def u128(self) -> int:
        return int.from_bytes(self.take(16), "little")

    def compact(self) -> int:
        n, self.off = compact_decode(self.data, self.off)
        return n

    def bytes_(self) -> bytes:
        n = self.compact()
        return self.take(n)

    def text(self) -> str:
        return self.bytes_().decode("utf-8", errors="replace")


def encode_contracts_api_call(
    origin: bytes,
    dest: bytes,
    value: int,
    gas_limit: tuple[int, int] | None,
    storage_deposit_limit: int | None,
    input_data: bytes,
) -> bytes:
    """Encode parameters for the `ContractsApi.call` runtime API."""
    if len(origin) != 32 or len(dest) != 32:
        raise ValueError("origin/dest must be 32-byte account ids")
    out = bytearray()
    out += origin
    out += dest
    out += u128(value)
    if gas_limit is None:
        out += b"\x00"
    else:
        out += b"\x01" + u64(gas_limit[0]) + u64(gas_limit[1])
    if storage_deposit_limit is None:
        out += b"\x00"
    else:
        out += b"\x01" + u128(storage_deposit_limit)
    out += scale_bytes(input_data)
    return bytes(out)


def decode_contract_exec_result(raw: bytes) -> dict:
    """Decode a `ContractExecResult` as returned by substrate-contracts-node 0.42.

    Empirically verified layout: a single Weight, then storage_deposit
    (enum + plain u128 Balance), debug_message, result, events.
    """
    d = Decoder(raw)
    gas = {"ref_time": d.u64(), "proof_size": d.u64()}
    deposit_variant = d.u8()
    storage_deposit: dict
    if deposit_variant == 0:
        storage_deposit = {"Charge": d.u128()}
    elif deposit_variant == 1:
        storage_deposit = {"Refund": d.u128()}
    else:
        storage_deposit = {"Empty": None}
    debug_message = d.text()
    result_variant = d.u8()
    if result_variant == 0:
        flags = d.u32()
        data = d.bytes_()
        result = {"Ok": {"flags": flags, "data": "0x" + data.hex()}}
    else:
        result = {"Err": {"raw": "0x" + d.data[d.off :].hex()}}
        d.off = len(d.data)
    return {
        "gas": gas,
        "storage_deposit": storage_deposit,
        "debug_message": debug_message,
        "result": result,
    }


REVERT_FLAG = 0x1


def decode_revert_reason(data: bytes) -> str | None:
    """Decode a solang-style revert payload on Polkadot.

    solang encodes `revert(string)` as the `Error(string)` selector (0x08c379a0)
    followed by a SCALE-encoded string (compact length + bytes), and panic
    aborts as the `Panic(uint256)` selector (0x4e487b71) followed by the panic
    code as raw (not 32-byte padded) bytes.
    """
    if not data:
        return None
    if data[:4] == bytes.fromhex("08c379a0") and len(data) > 4:
        try:
            n, off = compact_decode(data, 4)
            return data[off : off + n].decode("utf-8", errors="replace")
        except Exception:
            return None
    if data[:4] == bytes.fromhex("4e487b71") and len(data) > 4:
        code = int.from_bytes(data[4:], "little")  # SCALE u256 is little-endian
        return f"Panic(0x{code:02x})"
    return None
