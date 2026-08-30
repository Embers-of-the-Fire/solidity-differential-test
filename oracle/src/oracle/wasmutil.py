"""WASM post-processing helpers.

solang (v0.3.x) emits extra `soroban_*` function exports even when targeting
Polkadot. pallet-contracts rejects code whose export section contains function
exports other than `deploy` and `call`, so we strip the extra export entries.
The functions themselves remain in the module; only their visibility changes.
"""

from __future__ import annotations


def _leb_decode(buf: bytes, j: int) -> tuple[int, int]:
    shift = 0
    value = 0
    while True:
        b = buf[j]
        j += 1
        value |= (b & 0x7F) << shift
        shift += 7
        if not b & 0x80:
            return value, j


def _leb_encode(value: int) -> bytes:
    out = bytearray()
    while True:
        b = value & 0x7F
        value >>= 7
        if value:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def strip_function_exports(
    wasm: bytes, keep: tuple[str, ...] = ("deploy", "call")
) -> bytes:
    """Return the module with all function exports not in `keep` removed."""
    out = bytearray(wasm[:8])
    i = 8
    while i < len(wasm):
        sec = wasm[i]
        i += 1
        size, i = _leb_decode(wasm, i)
        body = wasm[i : i + size]
        i += size
        if sec == 7:  # export section
            j = 0
            n, j = _leb_decode(body, j)
            entries = []
            for _ in range(n):
                ln, j = _leb_decode(body, j)
                name = body[j : j + ln].decode()
                j += ln
                kind = body[j]
                j += 1
                idx, j = _leb_decode(body, j)
                entries.append((name, kind, idx))
            entries = [e for e in entries if e[1] != 0 or e[0] in keep]
            body = _leb_encode(len(entries))
            for name, kind, idx in entries:
                body += (
                    _leb_encode(len(name))
                    + name.encode()
                    + bytes([kind])
                    + _leb_encode(idx)
                )
        out.append(sec)
        out += _leb_encode(len(body))
        out += body
    return bytes(out)
