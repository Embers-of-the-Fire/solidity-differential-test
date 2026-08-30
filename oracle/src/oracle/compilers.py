"""Compiler drivers: solc (EVM bytecode) and solang (Polkadot/pallet-contracts WASM)."""

from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .wasmutil import strip_function_exports


@dataclass
class CompileOutcome:
    compiler: str
    ok: bool
    version: str = ""
    artifacts: dict[str, Any] | None = (
        None  # evm: {abi, bytecode}; solang: {wasm, metadata}
    )
    errors: list[str] | None = None
    warnings: list[str] | None = None

    def to_dict(self) -> dict:
        return {
            "compiler": self.compiler,
            "ok": self.ok,
            "version": self.version,
            "errors": self.errors,
            "warnings": self.warnings,
            "artifacts": {
                "abi": bool(self.artifacts and self.artifacts.get("abi")),
                "bytecode_bytes": len(self.artifacts.get("bytecode", b""))
                if self.artifacts
                else 0,
                "wasm_bytes": len(self.artifacts.get("wasm", b""))
                if self.artifacts
                else 0,
                "metadata": bool(self.artifacts and self.artifacts.get("metadata")),
            }
            if self.artifacts
            else None,
        }


def _tool_version(cmd: list[str], line: int = 0) -> str:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return (out.stdout.strip() or out.stderr.strip()).splitlines()[line]
    except Exception as e:  # pragma: no cover - defensive
        return f"unavailable: {e}"


def compile_solc(
    source: str, contract: str, settings: dict | None = None
) -> CompileOutcome:
    """Compile with solc via the standard-json interface."""
    settings = settings or {}
    version = _tool_version(["solc", "--version"], line=-1)
    std_input = {
        "language": "Solidity",
        "sources": {"input.sol": {"content": source}},
        "settings": {
            "optimizer": {
                "enabled": bool(settings.get("optimizer", False)),
                "runs": int(settings.get("optimizer_runs", 200)),
            },
            "outputSelection": {"*": {"*": ["abi", "evm.bytecode.object"]}},
        },
    }
    if "evm_version" in settings:
        std_input["settings"]["evmVersion"] = settings["evm_version"]

    proc = subprocess.run(
        ["solc", "--standard-json"],
        input=json.dumps(std_input),
        capture_output=True,
        text=True,
        timeout=120,
    )
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return CompileOutcome(
            "solc", False, version, errors=[proc.stderr or proc.stdout]
        )

    messages = out.get("errors", [])
    errors = [
        m.get("formattedMessage", m.get("message", ""))
        for m in messages
        if m.get("severity") == "error"
    ]
    warnings = [
        m.get("formattedMessage", m.get("message", ""))
        for m in messages
        if m.get("severity") == "warning"
    ]
    if errors or "contracts" not in out:
        return CompileOutcome(
            "solc",
            False,
            version,
            errors=errors or ["no contracts in output"],
            warnings=warnings,
        )

    try:
        compiled = out["contracts"]["input.sol"][contract]
        bytecode = bytes.fromhex(compiled["evm"]["bytecode"]["object"])
        abi = compiled["abi"]
    except KeyError:
        available = list(out.get("contracts", {}).get("input.sol", {}))
        return CompileOutcome(
            "solc",
            False,
            version,
            errors=[f"contract '{contract}' not found; available: {available}"],
            warnings=warnings,
        )
    return CompileOutcome(
        "solc",
        True,
        version,
        artifacts={"abi": abi, "bytecode": bytecode},
        warnings=warnings,
    )


def compile_solang(
    source: str, contract: str, settings: dict | None = None
) -> CompileOutcome:
    """Compile with solang --target polkadot; returns stripped WASM + metadata."""
    settings = settings or {}
    version = _tool_version(["solang", "--version"])
    opt_level = settings.get("opt_level", "default")

    with tempfile.TemporaryDirectory(prefix="solang-") as tmp:
        src_path = Path(tmp) / "input.sol"
        src_path.write_text(source)
        proc = subprocess.run(
            [
                "solang",
                "compile",
                "--target",
                "polkadot",
                "-O",
                str(opt_level),
                "-o",
                tmp,
                str(src_path),
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )
        if proc.returncode != 0:
            return CompileOutcome(
                "solang",
                False,
                version,
                errors=[proc.stderr.strip() or proc.stdout.strip()],
            )

        contract_file = Path(tmp) / f"{contract}.contract"
        if not contract_file.exists():
            produced = [p.name for p in Path(tmp).iterdir()]
            return CompileOutcome(
                "solang",
                False,
                version,
                errors=[
                    f"'{contract}.contract' not produced; got: {produced}; stderr: {proc.stderr.strip()}"
                ],
            )
        bundled = json.loads(contract_file.read_text())
        wasm = bytes.fromhex(bundled["source"]["wasm"][2:])
        stripped = strip_function_exports(wasm)
        warnings = [
            line for line in proc.stderr.splitlines() if "warning" in line.lower()
        ]
        return CompileOutcome(
            "solang",
            True,
            version,
            artifacts={"wasm": stripped, "metadata": bundled},
            warnings=warnings or None,
        )


def tool_versions() -> dict[str, str]:
    return {
        "solc": _tool_version(["solc", "--version"], line=-1),
        "solang": _tool_version(["solang", "--version"]),
        "anvil": _tool_version(["anvil", "--version"]),
        "substrate-contracts-node": _tool_version(
            ["substrate-contracts-node", "--version"]
        ),
    }
