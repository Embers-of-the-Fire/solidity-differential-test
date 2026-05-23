from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(slots=True)
class PolkadotRunResult:
    status: str
    return_data: str
    reason: str | None = None
    flags: int = 0
    events: tuple[dict[str, str], ...] = ()

    @property
    def reverted(self) -> bool:
        return bool(self.flags & 1)


class SealReturn(Exception):
    def __init__(self, flags: int, data: bytes) -> None:
        super().__init__("seal_return")
        self.flags = flags
        self.data = data


def run_polkadot_wasm_call(wasm_path: Path, calldata: str) -> PolkadotRunResult:
    return run_polkadot_wasm_entry(
        wasm_path,
        calldata,
        entrypoint="call",
        storage={},
    )


def run_polkadot_wasm_entry(
    wasm_path: Path,
    calldata: str,
    *,
    entrypoint: Literal["deploy", "call"] = "call",
    storage: dict[bytes, bytes] | None = None,
    caller: bytes | None = None,
    value: int = 0,
) -> PolkadotRunResult:
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
    events: list[dict[str, str]] = []
    storage_state = storage if storage is not None else {}
    caller_data = caller or (b"\x01" * 32)
    value_data = value.to_bytes(16, "little")
    engine = wasmtime.Engine()
    store = wasmtime.Store(engine)
    linker = wasmtime.Linker(engine)
    memory = wasmtime.Memory(
        store,
        wasmtime.MemoryType(wasmtime.Limits(16, 16)),
    )
    linker.define(store, "env", "memory", memory)

    def seal_return(caller_ctx, flags: int, ptr: int, length: int) -> None:
        data = bytes(memory.read(caller_ctx, ptr, ptr + length))
        captured.extend(data)
        raise SealReturn(flags, bytes(captured))

    def debug_message(_caller_ctx, _ptr: int, _length: int) -> int:
        return 0

    def input_host(caller_ctx, out_ptr: int, out_len_ptr: int) -> None:
        memory.write(caller_ctx, input_data, out_ptr)
        memory.write(caller_ctx, len(input_data).to_bytes(4, "little"), out_len_ptr)

    def value_transferred(caller_ctx, out_ptr: int, out_len_ptr: int) -> None:
        memory.write(caller_ctx, value_data, out_ptr)
        memory.write(caller_ctx, len(value_data).to_bytes(4, "little"), out_len_ptr)

    def caller_host(caller_ctx, out_ptr: int, out_len_ptr: int) -> None:
        memory.write(caller_ctx, caller_data, out_ptr)
        memory.write(caller_ctx, len(caller_data).to_bytes(4, "little"), out_len_ptr)

    def get_storage(
        caller_ctx, key_ptr: int, key_len: int, out_ptr: int, out_len_ptr: int
    ) -> int:
        key = bytes(memory.read(caller_ctx, key_ptr, key_ptr + key_len))
        value_bytes = storage_state.get(key)
        if value_bytes is None:
            return 1
        memory.write(caller_ctx, value_bytes, out_ptr)
        memory.write(caller_ctx, len(value_bytes).to_bytes(4, "little"), out_len_ptr)
        return 0

    def set_storage(
        caller_ctx, key_ptr: int, key_len: int, value_ptr: int, value_len: int
    ) -> int:
        key = bytes(memory.read(caller_ctx, key_ptr, key_ptr + key_len))
        value_bytes = bytes(memory.read(caller_ctx, value_ptr, value_ptr + value_len))
        storage_state[key] = value_bytes
        return 0

    def deposit_event(
        caller_ctx, topics_ptr: int, topics_len: int, data_ptr: int, data_len: int
    ) -> None:
        topics = bytes(memory.read(caller_ctx, topics_ptr, topics_ptr + topics_len))
        data = bytes(memory.read(caller_ctx, data_ptr, data_ptr + data_len))
        events.append({"topics": "0x" + topics.hex(), "data": "0x" + data.hex()})

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
        "caller",
        wasmtime.Func(
            store,
            wasmtime.FuncType([wasmtime.ValType.i32(), wasmtime.ValType.i32()], []),
            caller_host,
            access_caller=True,
        ),
    )
    linker.define(
        store,
        "seal0",
        "deposit_event",
        wasmtime.Func(
            store,
            wasmtime.FuncType(
                [
                    wasmtime.ValType.i32(),
                    wasmtime.ValType.i32(),
                    wasmtime.ValType.i32(),
                    wasmtime.ValType.i32(),
                ],
                [],
            ),
            deposit_event,
            access_caller=True,
        ),
    )
    linker.define(
        store,
        "seal1",
        "get_storage",
        wasmtime.Func(
            store,
            wasmtime.FuncType(
                [
                    wasmtime.ValType.i32(),
                    wasmtime.ValType.i32(),
                    wasmtime.ValType.i32(),
                    wasmtime.ValType.i32(),
                ],
                [wasmtime.ValType.i32()],
            ),
            get_storage,
            access_caller=True,
        ),
    )
    linker.define(
        store,
        "seal2",
        "set_storage",
        wasmtime.Func(
            store,
            wasmtime.FuncType(
                [
                    wasmtime.ValType.i32(),
                    wasmtime.ValType.i32(),
                    wasmtime.ValType.i32(),
                    wasmtime.ValType.i32(),
                ],
                [wasmtime.ValType.i32()],
            ),
            set_storage,
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
        exported = instance.exports(store)[entrypoint]
        exported(store)
    except SealReturn as returned:
        return PolkadotRunResult(
            status="revert" if returned.flags & 1 else "success",
            return_data="0x" + returned.data.hex(),
            flags=returned.flags,
            events=tuple(events),
        )
    except Exception as error:
        return PolkadotRunResult(
            status="error",
            return_data="",
            reason=str(error),
            events=tuple(events),
        )
    return PolkadotRunResult(
        status="success",
        return_data="0x",
        events=tuple(events),
    )
