from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .compiler import compile_with_solang, ensure_compilers_available
from .config import CampaignConfig
from .corpus import ensure_directories
from .io_oracle import encode_uint256_little
from .polkadot_runtime import PolkadotRunResult, run_polkadot_wasm_entry


@dataclass(slots=True)
class TransactionSmokeResult:
    status: str
    reason: str | None
    wasm_path: str | None
    steps: list[dict[str, Any]]
    storage_entries: int

    @property
    def passed(self) -> bool:
        return self.status == "pass"

    def to_json(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "wasm_path": self.wasm_path,
            "steps": self.steps,
            "storage_entries": self.storage_entries,
        }


def run_transaction_smoke(
    source_path: Path,
    config: CampaignConfig,
    work_dir: Path | None = None,
) -> TransactionSmokeResult:
    source_path = source_path.resolve()
    ensure_compilers_available()
    run_dir = work_dir or config.artifact_dir / "transaction-smoke" / source_path.stem
    ensure_directories([run_dir])
    polkadot_config = CampaignConfig(
        root_dir=config.root_dir,
        artifact_dir=config.artifact_dir,
        solang_target="polkadot",
        timeout_seconds=config.timeout_seconds,
        seed=config.seed,
    )
    compiled = compile_with_solang(source_path, polkadot_config, run_dir)
    if compiled.outcome != "success":
        return TransactionSmokeResult(
            status="fail",
            reason="Solang Polkadot compilation failed",
            wasm_path=None,
            steps=[compiled.to_json()],
            storage_entries=0,
        )

    wasm_path = next(
        (Path(path) for path in compiled.artifact_paths if path.endswith(".wasm")), None
    )
    if wasm_path is None:
        return TransactionSmokeResult(
            status="fail",
            reason="Solang produced no Polkadot Wasm artifact",
            wasm_path=None,
            steps=[compiled.to_json()],
            storage_entries=0,
        )

    storage: dict[bytes, bytes] = {}
    alice = b"\x01" * 32
    bob = b"\x02" * 32
    steps = [
        _run_step(
            "deploy new(5) from alice with value 10",
            wasm_path,
            storage,
            entrypoint="deploy",
            calldata="0x5816c425" + encode_uint256_little(5).removeprefix("0x"),
            caller=alice,
            value=10,
        ),
        _run_step(
            "query get() after deploy",
            wasm_path,
            storage,
            entrypoint="call",
            calldata="0x6d4ce63c",
            caller=alice,
            value=0,
            decode_uint256=True,
        ),
        _run_step(
            "tx increment(3) from bob with value 7",
            wasm_path,
            storage,
            entrypoint="call",
            calldata="0x7cf5dab0" + encode_uint256_little(3).removeprefix("0x"),
            caller=bob,
            value=7,
        ),
        _run_step(
            "query get() after increment",
            wasm_path,
            storage,
            entrypoint="call",
            calldata="0x6d4ce63c",
            caller=alice,
            value=0,
            decode_uint256=True,
        ),
        _run_step(
            "tx increment(0) should revert",
            wasm_path,
            storage,
            entrypoint="call",
            calldata="0x7cf5dab0" + encode_uint256_little(0).removeprefix("0x"),
            caller=alice,
            value=0,
        ),
    ]
    failed_step = next((step for step in steps if step["status"] == "error"), None)
    return TransactionSmokeResult(
        status="fail" if failed_step else "pass",
        reason=failed_step["reason"] if failed_step else None,
        wasm_path=str(wasm_path),
        steps=steps,
        storage_entries=len(storage),
    )


def format_transaction_smoke_text(result: TransactionSmokeResult) -> str:
    lines = [f"Transaction smoke: {result.status}"]
    if result.reason:
        lines.append(f"Reason: {result.reason}")
    if result.wasm_path:
        lines.append(f"Wasm: {result.wasm_path}")
    lines.append(f"Storage entries: {result.storage_entries}")
    lines.append("")
    lines.append("Observed runtime steps:")
    for index, step in enumerate(result.steps, start=1):
        name = step.get("name", step.get("compiler", f"step {index}"))
        lines.append(f"{index}. {name}: {step.get('status', step.get('outcome'))}")
        if step.get("decoded_uint256") is not None:
            lines.append(f"   decoded_uint256: {step['decoded_uint256']}")
        if step.get("return_data"):
            lines.append(f"   return_data: {step['return_data']}")
        if step.get("events"):
            lines.append(f"   events: {json.dumps(step['events'], sort_keys=True)}")
        if step.get("reason"):
            lines.append(f"   reason: {step['reason']}")
    return "\n".join(lines)


def _run_step(
    name: str,
    wasm_path: Path,
    storage: dict[bytes, bytes],
    *,
    entrypoint: str,
    calldata: str,
    caller: bytes,
    value: int,
    decode_uint256: bool = False,
) -> dict[str, Any]:
    result = run_polkadot_wasm_entry(
        wasm_path,
        calldata,
        entrypoint=entrypoint,  # type: ignore[arg-type]
        storage=storage,
        caller=caller,
        value=value,
    )
    step: dict[str, Any] = {
        "name": name,
        "entrypoint": entrypoint,
        "status": result.status,
        "return_data": result.return_data,
        "events": list(result.events),
        "flags": result.flags,
        "reason": result.reason,
    }
    if decode_uint256:
        step["decoded_uint256"] = _decode_optional_uint256_little(result)
    return step


def _decode_optional_uint256_little(result: PolkadotRunResult) -> int | None:
    data = bytes.fromhex(result.return_data.removeprefix("0x"))
    if len(data) < 32:
        return None
    return int.from_bytes(data[:32], "little")
