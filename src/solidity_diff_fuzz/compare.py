from __future__ import annotations

import difflib
import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from .compiler import compile_with_solang, compile_with_solc, ensure_compilers_available
from .config import CampaignConfig
from .corpus import ensure_directories
from .models import MismatchRecord, ProgramSpec, RenderedCase
from .oracle import compare_results
from .runtime import (
    RuntimeComparison,
    compare_evm_deployments,
    extract_solc_creation_bytecode,
)


@dataclass(slots=True)
class SourceComparison:
    source_path: Path
    solang_target: str
    solc: dict[str, Any]
    solang: dict[str, Any]
    differences: list[str]
    mismatch: dict[str, Any] | None
    outputs: dict[str, Any]
    stream_diffs: dict[str, Any]
    runtime: dict[str, Any] | None = None

    @property
    def has_difference(self) -> bool:
        return bool(self.differences)

    def to_json(self) -> dict[str, Any]:
        return {
            "source_path": str(self.source_path),
            "solang_target": self.solang_target,
            "differences": self.differences,
            "mismatch": self.mismatch,
            "outputs": self.outputs,
            "stream_diffs": self.stream_diffs,
            "solc": self.solc,
            "solang": self.solang,
            "runtime": self.runtime,
        }


@dataclass(slots=True)
class HarnessCheck:
    status: str
    compile_status: str
    runtime_status: str
    reason: str | None
    comparison: SourceComparison

    @property
    def passed(self) -> bool:
        return self.status == "pass"

    def to_json(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "compile_status": self.compile_status,
            "runtime_status": self.runtime_status,
            "reason": self.reason,
            "comparison": self.comparison.to_json(),
        }


def compare_source_file(
    source_path: Path,
    config: CampaignConfig,
    work_dir: Path | None = None,
    include_runtime: bool = False,
    calldata: str | None = None,
) -> SourceComparison:
    source_path = source_path.resolve()
    if not source_path.exists():
        msg = f"Solidity source does not exist: {source_path}"
        raise FileNotFoundError(msg)
    if not source_path.is_file():
        msg = f"Solidity source is not a file: {source_path}"
        raise IsADirectoryError(msg)

    ensure_compilers_available()
    source = source_path.read_text(encoding="utf-8")
    case = _case_from_source(source_path, source)
    run_dir = work_dir or _default_work_dir(config, source_path)
    ensure_directories([run_dir])

    solc = compile_with_solc(source_path, config, run_dir)
    solang = compile_with_solang(source_path, config, run_dir)
    mismatch = compare_results(case, solc, solang)
    solc_artifact_paths = _write_solc_artifacts(solc.stdout, run_dir, source_path.stem)
    solc_json = solc.to_json()
    solc_json["artifact_paths"] = [str(path) for path in solc_artifact_paths]
    solang_json = solang.to_json()
    outputs = {
        "solc": _output_metadata(solc_json),
        "solang": _output_metadata(solang_json),
    }
    runtime = None
    if include_runtime:
        runtime = compare_evm_deployments(solc, solang, config, calldata).to_json()
    return SourceComparison(
        source_path=source_path,
        solang_target=config.solang_target,
        solc=solc_json,
        solang=solang_json,
        differences=_difference_items(solc_json, solang_json),
        mismatch=_mismatch_json(mismatch),
        outputs=outputs,
        stream_diffs=_stream_diffs(solc_json, solang_json),
        runtime=runtime,
    )


def format_comparison_text(comparison: SourceComparison) -> str:
    status = "different" if comparison.has_difference else "same compiler outcome"
    lines = [
        f"Source: {comparison.source_path}",
        f"Solang target: {comparison.solang_target}",
        f"Summary: {status}",
        "",
        "Differences:",
    ]
    if comparison.differences:
        lines.extend(f"- {item}" for item in comparison.differences)
    else:
        lines.append("- none")

    if comparison.mismatch is not None:
        lines.extend(
            [
                "",
                "Interesting mismatch:",
                f"- kind: {comparison.mismatch['kind']}",
                f"- signature: {comparison.mismatch['signature']}",
                f"- summary: {comparison.mismatch['summary']}",
            ]
        )

    if comparison.runtime is not None:
        lines.extend(_format_runtime_result(comparison.runtime))

    lines.extend(_format_stream_diffs(comparison.stream_diffs))
    lines.extend(_format_outputs(comparison.outputs))

    lines.extend(["", "Compiler results:"])
    lines.extend(_format_compiler_result("solc", comparison.solc))
    lines.extend(_format_compiler_result("solang", comparison.solang))
    return "\n".join(lines)


def format_comparison_json(comparison: SourceComparison) -> str:
    return json.dumps(comparison.to_json(), indent=2, sort_keys=True)


def run_harness_check(
    source_path: Path,
    config: CampaignConfig,
    work_dir: Path | None = None,
    calldata: str | None = None,
) -> HarnessCheck:
    comparison = compare_source_file(
        source_path, config, work_dir=work_dir, include_runtime=True, calldata=calldata
    )
    compile_status = "different" if comparison.has_difference else "same"
    runtime = comparison.runtime
    runtime_status = runtime["status"] if runtime is not None else "unavailable"

    if compile_status != "same":
        return HarnessCheck(
            status="fail",
            compile_status=compile_status,
            runtime_status=runtime_status,
            reason="compile outputs differ; runtime differential cannot be trusted",
            comparison=comparison,
        )
    if runtime_status == "unavailable":
        reason = runtime["reason"] if runtime is not None else "runtime was not run"
        return HarnessCheck(
            status="fail",
            compile_status=compile_status,
            runtime_status=runtime_status,
            reason=f"runtime comparison unavailable: {reason}",
            comparison=comparison,
        )
    if runtime_status != "same":
        return HarnessCheck(
            status="fail",
            compile_status=compile_status,
            runtime_status=runtime_status,
            reason="runtime observations differ",
            comparison=comparison,
        )
    return HarnessCheck(
        status="pass",
        compile_status=compile_status,
        runtime_status=runtime_status,
        reason=None,
        comparison=comparison,
    )


def format_harness_check_text(check: HarnessCheck) -> str:
    lines = [
        f"Harness check: {check.status}",
        f"Compile phase: {check.compile_status}",
        f"Runtime phase: {check.runtime_status}",
    ]
    if check.reason:
        lines.append(f"Reason: {check.reason}")
    lines.extend(["", format_comparison_text(check.comparison)])
    return "\n".join(lines)


def compare_runtime_results(runtime: RuntimeComparison) -> dict[str, Any]:
    return runtime.to_json()


def _case_from_source(source_path: Path, source: str) -> RenderedCase:
    return RenderedCase(
        case_id=source_path.stem,
        spec=ProgramSpec(
            base_template="external-source",
            state_templates=[],
            function_templates=[],
            context={"contract_name": source_path.stem},
        ),
        source=source,
        source_path=source_path,
    )


def _default_work_dir(config: CampaignConfig, source_path: Path) -> Path:
    return config.artifact_dir / "compare" / source_path.stem


def _write_solc_artifacts(stdout: str, work_dir: Path, name: str) -> tuple[Path, ...]:
    bytecode = extract_solc_creation_bytecode(stdout)
    if bytecode is None:
        return ()
    artifact_dir = work_dir / "solc-artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / f"{name}.bin"
    artifact_path.write_text(f"{bytecode}\n", encoding="utf-8")
    return (artifact_path,)


def _output_metadata(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "stdout_sha256": sha256(result["stdout"].encode()).hexdigest(),
        "stderr_sha256": sha256(result["stderr"].encode()).hexdigest(),
        "artifacts": [_artifact_metadata(path) for path in result["artifact_paths"]],
    }


def _stream_diffs(solc: dict[str, Any], solang: dict[str, Any]) -> dict[str, Any]:
    return {
        "stdout": _stream_diff(solc["stdout"], solang["stdout"]),
        "stderr": _stream_diff(solc["stderr"], solang["stderr"]),
    }


def _stream_diff(left: str, right: str, max_lines: int = 80) -> dict[str, Any]:
    if left == right:
        return {"different": False, "truncated": False, "lines": []}
    lines = list(
        difflib.unified_diff(
            left.splitlines(),
            right.splitlines(),
            fromfile="solc",
            tofile="solang",
            lineterm="",
        )
    )
    truncated = len(lines) > max_lines
    if truncated:
        lines = lines[:max_lines]
        lines.append(f"... diff truncated after {max_lines} lines ...")
    return {"different": True, "truncated": truncated, "lines": lines}


def _artifact_metadata(path_value: str) -> dict[str, Any]:
    path = Path(path_value)
    data = path.read_bytes()
    return {
        "path": str(path),
        "name": path.name,
        "suffix": path.suffix,
        "size_bytes": len(data),
        "sha256": sha256(data).hexdigest(),
    }


def _difference_items(solc: dict[str, Any], solang: dict[str, Any]) -> list[str]:
    differences: list[str] = []
    _append_if_different(differences, solc, solang, "outcome")
    _append_if_different(differences, solc, solang, "diagnostic_kind")
    _append_if_different(differences, solc, solang, "exit_code")

    if solc["stdout"] != solang["stdout"]:
        differences.append("stdout differs")
    if solc["stderr"] != solang["stderr"]:
        differences.append("stderr differs")
    return differences


def _append_if_different(
    differences: list[str], solc: dict[str, Any], solang: dict[str, Any], key: str
) -> None:
    if solc[key] != solang[key]:
        differences.append(f"{key}: solc={solc[key]!r}, solang={solang[key]!r}")


def _mismatch_json(mismatch: MismatchRecord | None) -> dict[str, Any] | None:
    if mismatch is None:
        return None
    return {
        "kind": mismatch.kind.value,
        "signature": mismatch.signature,
        "summary": mismatch.summary,
    }


def _format_compiler_result(label: str, result: dict[str, Any]) -> list[str]:
    lines = [
        f"- {label}:",
        f"  command: {' '.join(result['command'])}",
        f"  outcome: {result['outcome']}",
        f"  diagnostic_kind: {result['diagnostic_kind']}",
        f"  exit_code: {result['exit_code']}",
    ]
    artifacts = result["artifact_paths"]
    if artifacts:
        lines.append(f"  artifacts: {', '.join(artifacts)}")
    if result["stderr"]:
        lines.append(f"  stderr: {_first_line(result['stderr'])}")
    return lines


def _first_line(text: str) -> str:
    return text.splitlines()[0] if text.splitlines() else ""


def _format_runtime_result(runtime: dict[str, Any]) -> list[str]:
    lines = ["", "Runtime comparison:", f"- status: {runtime['status']}"]
    if runtime["reason"]:
        lines.append(f"- reason: {runtime['reason']}")
    if runtime["differences"]:
        lines.append("- differences: " + "; ".join(runtime["differences"]))
    return lines


def _format_stream_diffs(stream_diffs: dict[str, Any]) -> list[str]:
    lines = ["", "Exact stream diffs:"]
    any_diff = False
    for name in ("stdout", "stderr"):
        stream = stream_diffs[name]
        if not stream["different"]:
            continue
        any_diff = True
        lines.append(f"- {name}:")
        lines.extend(f"  {line}" for line in stream["lines"])
    if not any_diff:
        lines.append("- none")
    return lines


def _format_outputs(outputs: dict[str, Any]) -> list[str]:
    lines = ["", "Compiler outputs:"]
    for compiler in ("solc", "solang"):
        artifacts = outputs[compiler]["artifacts"]
        lines.append(f"- {compiler}: {len(artifacts)} artifact(s)")
        if not artifacts:
            lines.append("  artifacts: none")
        for artifact in artifacts:
            lines.append(
                "  artifact: "
                f"{artifact['name']} "
                f"({artifact['size_bytes']} bytes, sha256={artifact['sha256'][:16]})"
            )
    return lines
