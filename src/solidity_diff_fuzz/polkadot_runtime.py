from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class PolkadotRunResult:
    status: str
    return_data: str
    reason: str | None = None


class SealReturn(Exception):
    def __init__(self, data: bytes) -> None:
        super().__init__("seal_return")
        self.data = data


def run_polkadot_wasm_call(wasm_path: Path, calldata: str) -> PolkadotRunResult:
    try:
        import wasmtime
    except ImportError:
        return PolkadotRunResult(
            status="unavailable",
            return_data="",
            reason="Python wasmtime package is not installed",
        )

    input_data = bytes.fromhex(calldata.removeprefix("0x"))
    captured = bytearray()
    engine = wasmtime.Engine()
    store = wasmtime.Store(engine)
    linker = wasmtime.Linker(engine)
    memory = wasmtime.Memory(
        store,
        wasmtime.MemoryType(wasmtime.Limits(16, 16)),
    )
    linker.define(store, "env", "memory", memory)

    def seal_return(caller, _flags: int, ptr: int, length: int) -> None:
        data = bytes(memory.read(caller, ptr, ptr + length))
        captured.extend(data)
        raise SealReturn(bytes(captured))

    def debug_message(caller, _ptr: int, _length: int) -> int:
        return 0

    def input_host(caller, out_ptr: int, out_len_ptr: int) -> None:
        memory.write(caller, input_data, out_ptr)
        memory.write(caller, len(input_data).to_bytes(4, "little"), out_len_ptr)

    def value_transferred(caller, out_ptr: int, out_len_ptr: int) -> None:
        memory.write(caller, b"\x00" * 16, out_ptr)
        memory.write(caller, (16).to_bytes(4, "little"), out_len_ptr)

    linker.define(
        store,
        "seal0",
        "seal_return",
        wasmtime.Func(
            store,
            wasmtime.FuncType(
                [
                    wasmtime.ValType.i32(),
                    wasmtime.ValType.i32(),
                    wasmtime.ValType.i32(),
                ],
                [],
            ),
            seal_return,
            access_caller=True,
        ),
    )
    linker.define(
        store,
        "seal0",
        "debug_message",
        wasmtime.Func(
            store,
            wasmtime.FuncType(
                [wasmtime.ValType.i32(), wasmtime.ValType.i32()],
                [wasmtime.ValType.i32()],
            ),
            debug_message,
            access_caller=True,
        ),
    )
    linker.define(
        store,
        "seal0",
        "input",
        wasmtime.Func(
            store,
            wasmtime.FuncType([wasmtime.ValType.i32(), wasmtime.ValType.i32()], []),
            input_host,
            access_caller=True,
        ),
    )
    linker.define(
        store,
        "seal0",
        "value_transferred",
        wasmtime.Func(
            store,
            wasmtime.FuncType([wasmtime.ValType.i32(), wasmtime.ValType.i32()], []),
            value_transferred,
            access_caller=True,
        ),
    )

    try:
        module = wasmtime.Module.from_file(engine, wasm_path)
        instance = linker.instantiate(store, module)
        call = instance.exports(store)["call"]
        call(store)
    except SealReturn as returned:
        return PolkadotRunResult(
            status="success", return_data="0x" + returned.data.hex()
        )
    except Exception as error:
        return PolkadotRunResult(status="error", return_data="", reason=str(error))
    return PolkadotRunResult(
        status="error",
        return_data="",
        reason="contract returned without seal_return",
    )
