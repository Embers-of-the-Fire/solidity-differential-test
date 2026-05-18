from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .compiler import compile_with_solc, ensure_compilers_available
from .config import CampaignConfig
from .corpus import ensure_directories
from .models import CompilerResult, OutcomeKind
from .normalize import normalize_text

BYTECODE_RE = re.compile(r"(?:Binary:|Binary of the runtime part:)\s*\n([0-9a-fA-F]+)")


@dataclass(slots=True)
class EvmObservation:
    status: str
    failure_kind: str
    return_data: str
    stderr: str
    exit_code: int | None

    def to_json(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "failure_kind": self.failure_kind,
            "return_data": self.return_data,
            "stderr": self.stderr,
            "exit_code": self.exit_code,
        }


@dataclass(slots=True)
class RuntimeComparison:
    status: str
    reason: str | None
    differences: list[str]
    solc: dict[str, Any] | None
    solang: dict[str, Any] | None

    @property
    def has_difference(self) -> bool:
        return bool(self.differences)

    def to_json(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "differences": self.differences,
            "solc": self.solc,
            "solang": self.solang,
        }


@dataclass(slots=True)
class RuntimeSmokeResult:
    source_path: Path
    status: str
    reason: str | None
    solc: dict[str, Any]
    observation: dict[str, Any] | None

    def to_json(self) -> dict[str, Any]:
        return {
            "source_path": str(self.source_path),
            "status": self.status,
            "reason": self.reason,
            "solc": self.solc,
            "observation": self.observation,
        }


def run_runtime_smoke(
    source_path: Path,
    config: CampaignConfig,
    work_dir: Path | None = None,
) -> RuntimeSmokeResult:
    source_path = source_path.resolve()
    ensure_compilers_available()
    run_dir = work_dir or config.artifact_dir / "runtime-smoke" / source_path.stem
    ensure_directories([run_dir])
    solc = compile_with_solc(source_path, config, run_dir)
    solc_json = solc.to_json()
    if solc.outcome != OutcomeKind.SUCCESS:
        return RuntimeSmokeResult(
            source_path=source_path,
            status="unavailable",
            reason="solc must succeed before runtime smoke can execute",
            solc=solc_json,
            observation=None,
        )
    bytecode = extract_solc_creation_bytecode(solc.stdout)
    if bytecode is None:
        return RuntimeSmokeResult(
            source_path=source_path,
            status="unavailable",
            reason="could not extract solc creation bytecode",
            solc=solc_json,
            observation=None,
        )
    if shutil.which("evm") is None:
        return RuntimeSmokeResult(
            source_path=source_path,
            status="unavailable",
            reason="evm runner is not available in PATH",
            solc=solc_json,
            observation=None,
        )

    observation = run_evm_create(bytecode, config.timeout_seconds)
    return RuntimeSmokeResult(
        source_path=source_path,
        status=observation.status,
        reason=None if observation.status == "success" else observation.stderr,
        solc=solc_json,
        observation=observation.to_json(),
    )


def format_runtime_smoke_text(result: RuntimeSmokeResult) -> str:
    lines = [
        f"Source: {result.source_path}",
        f"Runtime smoke: {result.status}",
    ]
    if result.reason:
        lines.append(f"Reason: {result.reason}")
    lines.extend(
        [
            "",
            "Compiler result:",
            f"- solc outcome: {result.solc['outcome']}",
            f"- solc diagnostic_kind: {result.solc['diagnostic_kind']}",
            f"- solc exit_code: {result.solc['exit_code']}",
        ]
    )
    if result.observation is not None:
        return_data = result.observation["return_data"]
        lines.extend(
            [
                "",
                "EVM observation:",
                f"- status: {result.observation['status']}",
                f"- failure_kind: {result.observation['failure_kind']}",
                f"- exit_code: {result.observation['exit_code']}",
                f"- return_data_prefix: {return_data[:66]}",
            ]
        )
    return "\n".join(lines)


def compare_evm_deployments(
    solc: CompilerResult,
    solang: CompilerResult,
    config: CampaignConfig,
    calldata: str | None = None,
) -> RuntimeComparison:
    if solc.outcome != OutcomeKind.SUCCESS or solang.outcome != OutcomeKind.SUCCESS:
        return _unavailable("both compilers must succeed before runtime comparison")

    solc_bytecode = extract_solc_creation_bytecode(solc.stdout)
    if solc_bytecode is None:
        return _unavailable("could not extract solc creation bytecode")

    solang_bytecode = extract_solang_creation_bytecode(solang.artifact_paths)
    if solang_bytecode is None:
        return _unavailable("could not find solang EVM creation bytecode artifact")

    if shutil.which("evm") is None:
        return _unavailable("evm runner is not available in PATH")

    solc_deploy = run_evm_create(solc_bytecode, config.timeout_seconds)
    solang_deploy = run_evm_create(solang_bytecode, config.timeout_seconds)
    differences = _prefixed_differences(
        "deploy", compare_observations(solc_deploy, solang_deploy)
    )
    solc_runtime = {"deploy": solc_deploy.to_json(), "call": None}
    solang_runtime = {"deploy": solang_deploy.to_json(), "call": None}

    if calldata is not None:
        if solc_deploy.status != "success" or solang_deploy.status != "success":
            differences.append("call: skipped because deployment failed")
        else:
            solc_call = run_evm_call(
                solc_deploy.return_data, calldata, config.timeout_seconds
            )
            solang_call = run_evm_call(
                solang_deploy.return_data, calldata, config.timeout_seconds
            )
            solc_runtime["call"] = solc_call.to_json()
            solang_runtime["call"] = solang_call.to_json()
            differences.extend(
                _prefixed_differences(
                    "call", compare_observations(solc_call, solang_call)
                )
            )
    return RuntimeComparison(
        status="different" if differences else "same",
        reason=None,
        differences=differences,
        solc=solc_runtime,
        solang=solang_runtime,
    )


def run_evm_create(bytecode: str, timeout_seconds: int) -> EvmObservation:
    command = ("evm", "run", "--create", bytecode)
    return _run_evm(command, timeout_seconds)


def run_evm_call(bytecode: str, calldata: str, timeout_seconds: int) -> EvmObservation:
    command = ("evm", "run", "--input", calldata, bytecode)
    return _run_evm(command, timeout_seconds)


def _run_evm(command: tuple[str, ...], timeout_seconds: int) -> EvmObservation:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        stderr = error.stderr if isinstance(error.stderr, str) else ""
        return EvmObservation(
            status="timeout",
            failure_kind="timeout",
            return_data="",
            stderr=normalize_text(stderr),
            exit_code=None,
        )

    stderr = normalize_text(completed.stderr)
    stdout = normalize_text(completed.stdout)
    raw_status = "success" if completed.returncode == 0 else "error"
    failure_kind = classify_evm_failure(raw_status, stdout, stderr)
    status = (
        "success" if raw_status == "success" and failure_kind == "none" else "error"
    )
    return EvmObservation(
        status=status,
        failure_kind=failure_kind,
        return_data=stdout,
        stderr=stderr,
        exit_code=completed.returncode,
    )


def _prefixed_differences(prefix: str, differences: list[str]) -> list[str]:
    return [f"{prefix}: {difference}" for difference in differences]


def compare_observations(left: EvmObservation, right: EvmObservation) -> list[str]:
    differences: list[str] = []
    if left.status != right.status:
        differences.append(f"status: solc={left.status!r}, solang={right.status!r}")
    if left.failure_kind != right.failure_kind:
        differences.append(
            f"failure_kind: solc={left.failure_kind!r}, solang={right.failure_kind!r}"
        )
    if left.return_data != right.return_data:
        differences.append("return_data differs")
    if left.stderr != right.stderr:
        differences.append("stderr differs")
    if left.exit_code != right.exit_code:
        differences.append(
            f"exit_code: solc={left.exit_code!r}, solang={right.exit_code!r}"
        )
    return differences


def classify_evm_failure(status: str, stdout: str, stderr: str) -> str:
    return_data = stdout.removeprefix("0x").lower()
    if return_data.startswith("4e487b71"):
        return "panic"
    if return_data.startswith("08c379a0"):
        return "revert"
    normalized = f"{stdout}\n{stderr}".lower()
    if "execution reverted" in normalized:
        return "revert"
    if "invalid opcode" in normalized:
        return "invalid-opcode"
    if "out of gas" in normalized:
        return "out-of-gas"
    if "panic" in normalized:
        return "panic"
    if status == "success":
        return "none"
    return "vm-error"


def extract_solc_creation_bytecode(stdout: str) -> str | None:
    matches = BYTECODE_RE.findall(stdout)
    return matches[0] if matches else None


def extract_solang_creation_bytecode(artifact_paths: tuple[str, ...]) -> str | None:
    for artifact_path in artifact_paths:
        path = Path(artifact_path)
        if path.suffix == ".bin":
            text = path.read_text(encoding="utf-8").strip()
            if text:
                return text
    return None


def _unavailable(reason: str) -> RuntimeComparison:
    return RuntimeComparison(
        status="unavailable",
        reason=reason,
        differences=[],
        solc=None,
        solang=None,
    )
