from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .compiler import compile_with_solang, compile_with_solc, ensure_compilers_available
from .config import CampaignConfig
from .corpus import ensure_directories
from .models import CompilerResult, OutcomeKind
from .polkadot_runtime import run_polkadot_wasm_call
from .runtime import (
    EvmObservation,
    extract_solang_creation_bytecode,
    extract_solc_creation_bytecode,
    run_evm_call,
    run_evm_create,
)


@dataclass(slots=True)
class RuntimeSideResult:
    compiler: str
    target: str
    status: str
    reason: str | None
    compile_result: dict[str, Any]
    deploy: dict[str, Any] | None
    call: dict[str, Any] | None
    matches_expected: bool | None

    def to_json(self) -> dict[str, Any]:
        return {
            "compiler": self.compiler,
            "target": self.target,
            "status": self.status,
            "reason": self.reason,
            "compile_result": self.compile_result,
            "deploy": self.deploy,
            "call": self.call,
            "matches_expected": self.matches_expected,
        }


@dataclass(slots=True)
class RuntimeDiffTest:
    status: str
    reason: str | None
    expected: str
    solc: RuntimeSideResult
    solang: RuntimeSideResult
    differences: list[str]

    @property
    def passed(self) -> bool:
        return self.status == "pass"

    def to_json(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "expected": self.expected,
            "differences": self.differences,
            "solc": self.solc.to_json(),
            "solang": self.solang.to_json(),
        }


def run_runtime_diff_test(
    source_path: Path,
    config: CampaignConfig,
    calldata: str,
    expected: str,
    expected_solang: str | None = None,
    calldata_solang: str | None = None,
    work_dir: Path | None = None,
) -> RuntimeDiffTest:
    source_path = source_path.resolve()
    ensure_compilers_available()
    run_dir = work_dir or config.artifact_dir / "runtime-diff" / source_path.stem
    ensure_directories([run_dir])

    solc = compile_with_solc(source_path, config, run_dir)
    solang = compile_with_solang(source_path, config, run_dir)
    solc_result = run_solc_evm_side(solc, config, calldata, expected)
    solang_result = run_solang_side(
        solang, config, calldata_solang or calldata, expected_solang or expected
    )
    differences = compare_runtime_sides(solc_result, solang_result)
    status, reason = classify_runtime_diff(solc_result, solang_result, differences)
    return RuntimeDiffTest(
        status=status,
        reason=reason,
        expected=normalize_hex(expected),
        solc=solc_result,
        solang=solang_result,
        differences=differences,
    )


def run_solc_evm_side(
    result: CompilerResult, config: CampaignConfig, calldata: str, expected: str
) -> RuntimeSideResult:
    if result.outcome != OutcomeKind.SUCCESS:
        return _side_unavailable("solc", "evm", result, "compile failed")
    creation = extract_solc_creation_bytecode(result.stdout)
    if creation is None:
        return _side_unavailable(
            "solc", "evm", result, "could not extract creation bytecode"
        )
    return _run_evm_side("solc", "evm", result, creation, config, calldata, expected)


def run_solang_side(
    result: CompilerResult, config: CampaignConfig, calldata: str, expected: str
) -> RuntimeSideResult:
    if result.outcome != OutcomeKind.SUCCESS:
        return _side_unavailable(
            "solang", config.solang_target, result, "compile failed"
        )
    if config.solang_target == "evm":
        creation = extract_solang_creation_bytecode(result.artifact_paths)
        if creation is None:
            return _side_unavailable(
                "solang",
                "evm",
                result,
                "Solang emitted no EVM bytecode artifact",
            )
        return _run_evm_side(
            "solang", "evm", result, creation, config, calldata, expected
        )
    if config.solang_target == "polkadot":
        wasm_path = _find_artifact(result.artifact_paths, ".wasm")
        if wasm_path is None:
            return _side_unavailable(
                "solang", "polkadot", result, "Solang emitted no Polkadot Wasm artifact"
            )
        run = run_polkadot_wasm_call(wasm_path, calldata)
        if run.status != "success":
            return RuntimeSideResult(
                compiler="solang",
                target="polkadot",
                status="failed" if run.status == "error" else "unavailable",
                reason=run.reason,
                compile_result=result.to_json(),
                deploy=None,
                call={
                    "status": run.status,
                    "failure_kind": "host-error"
                    if run.status == "error"
                    else run.status,
                    "return_data": run.return_data,
                    "stderr": run.reason or "",
                    "exit_code": None,
                },
                matches_expected=None,
            )
        actual_output = normalize_hex(run.return_data)
        return RuntimeSideResult(
            compiler="solang",
            target="polkadot",
            status="ran",
            reason=None,
            compile_result=result.to_json(),
            deploy=None,
            call={
                "status": "success",
                "failure_kind": "none",
                "return_data": actual_output,
                "stderr": "",
                "exit_code": None,
            },
            matches_expected=actual_output == normalize_hex(expected),
        )
    return _side_unavailable(
        "solang",
        config.solang_target,
        result,
        f"runtime backend for Solang target {config.solang_target!r} is unavailable",
    )


def compare_runtime_sides(
    solc: RuntimeSideResult, solang: RuntimeSideResult
) -> list[str]:
    differences: list[str] = []
    if solc.matches_expected and solang.matches_expected:
        return differences
    if solc.status != solang.status:
        differences.append(f"status: solc={solc.status!r}, solang={solang.status!r}")
    if solc.call and solang.call:
        for key in ("status", "failure_kind", "return_data"):
            if solc.call[key] != solang.call[key]:
                differences.append(
                    f"call.{key}: solc={solc.call[key]!r}, solang={solang.call[key]!r}"
                )
    if solc.matches_expected != solang.matches_expected:
        differences.append(
            "matches_expected: "
            f"solc={solc.matches_expected!r}, solang={solang.matches_expected!r}"
        )
    return differences


def classify_runtime_diff(
    solc: RuntimeSideResult, solang: RuntimeSideResult, differences: list[str]
) -> tuple[str, str | None]:
    if solc.status == "unavailable" or solang.status == "unavailable":
        return ("fail", "one or both runtime sides are unavailable")
    if solc.matches_expected and solang.matches_expected:
        return ("pass", None)
    if differences:
        return ("different", "runtime behavior differs")
    return ("fail", "both sides ran but did not match expected output")


def format_runtime_diff_text(result: RuntimeDiffTest) -> str:
    lines = [
        f"Runtime differential test: {result.status}",
        f"Expected return: {result.expected}",
    ]
    if result.reason:
        lines.append(f"Reason: {result.reason}")
    lines.extend(["", "Differences:"])
    lines.extend(f"- {difference}" for difference in result.differences)
    if not result.differences:
        lines.append("- none")
    lines.extend(["", "Runtime sides:"])
    lines.extend(_format_side(result.solc))
    lines.extend(_format_side(result.solang))
    return "\n".join(lines)


def format_runtime_diff_json(result: RuntimeDiffTest) -> str:
    return json.dumps(result.to_json(), indent=2, sort_keys=True)


def normalize_hex(value: str) -> str:
    return "0x" + value.removeprefix("0x").lower()


def _run_evm_side(
    compiler: str,
    target: str,
    result: CompilerResult,
    creation: str,
    config: CampaignConfig,
    calldata: str,
    expected: str,
) -> RuntimeSideResult:
    deploy = run_evm_create(creation, config.timeout_seconds)
    call: EvmObservation | None = None
    if deploy.status == "success":
        call = run_evm_call(deploy.return_data, calldata, config.timeout_seconds)
    expected_output = normalize_hex(expected)
    actual_output = normalize_hex(call.return_data) if call is not None else None
    return RuntimeSideResult(
        compiler=compiler,
        target=target,
        status="ran" if call is not None else "failed",
        reason=None if call is not None else "deployment failed before call",
        compile_result=result.to_json(),
        deploy=deploy.to_json(),
        call=call.to_json() if call is not None else None,
        matches_expected=actual_output == expected_output
        if actual_output is not None
        else None,
    )


def _side_unavailable(
    compiler: str, target: str, result: CompilerResult, reason: str
) -> RuntimeSideResult:
    return RuntimeSideResult(
        compiler=compiler,
        target=target,
        status="unavailable",
        reason=reason,
        compile_result=result.to_json(),
        deploy=None,
        call=None,
        matches_expected=None,
    )


def _find_artifact(artifact_paths: tuple[str, ...], suffix: str) -> Path | None:
    for artifact_path in artifact_paths:
        path = Path(artifact_path)
        if path.suffix == suffix:
            return path
    return None


def _format_side(side: RuntimeSideResult) -> list[str]:
    lines = [
        f"- {side.compiler} ({side.target}): {side.status}",
        f"  compile_outcome: {side.compile_result['outcome']}",
        f"  matches_expected: {side.matches_expected}",
    ]
    if side.reason:
        lines.append(f"  reason: {side.reason}")
    if side.call:
        lines.append(f"  call_status: {side.call['status']}")
        lines.append(f"  call_failure_kind: {side.call['failure_kind']}")
        lines.append(f"  call_return: {side.call['return_data']}")
    return lines
