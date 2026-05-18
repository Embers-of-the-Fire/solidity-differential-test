from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .compare import SourceComparison, compare_source_file, format_comparison_text
from .config import CampaignConfig
from .normalize import normalize_text


@dataclass(slots=True)
class ArtifactValidation:
    path: str
    kind: str
    status: str
    stderr: str

    def to_json(self) -> dict[str, str]:
        return {
            "path": self.path,
            "kind": self.kind,
            "status": self.status,
            "stderr": self.stderr,
        }


@dataclass(slots=True)
class TargetCheck:
    status: str
    reason: str | None
    comparison: SourceComparison
    validations: list[ArtifactValidation]

    @property
    def passed(self) -> bool:
        return self.status == "pass"

    def to_json(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "comparison": self.comparison.to_json(),
            "validations": [validation.to_json() for validation in self.validations],
        }


def run_target_check(
    source_path: Path,
    config: CampaignConfig,
    work_dir: Path | None = None,
) -> TargetCheck:
    comparison = compare_source_file(source_path, config, work_dir=work_dir)
    validations = validate_solang_artifacts(comparison.solang["artifact_paths"])
    if (
        comparison.solc["outcome"] != "success"
        or comparison.solang["outcome"] != "success"
    ):
        return TargetCheck(
            status="fail",
            reason="one or both compilers failed before target validation",
            comparison=comparison,
            validations=validations,
        )
    if not validations:
        return TargetCheck(
            status="fail",
            reason="Solang produced no target artifact that this harness can validate",
            comparison=comparison,
            validations=validations,
        )
    failed = [
        validation for validation in validations if validation.status != "success"
    ]
    if failed:
        return TargetCheck(
            status="fail",
            reason="one or more Solang target artifacts failed validation",
            comparison=comparison,
            validations=validations,
        )
    return TargetCheck(
        status="pass",
        reason=None,
        comparison=comparison,
        validations=validations,
    )


def validate_solang_artifacts(artifact_paths: list[str]) -> list[ArtifactValidation]:
    validations: list[ArtifactValidation] = []
    for artifact_path in artifact_paths:
        path = Path(artifact_path)
        if path.suffix == ".wasm":
            validations.append(validate_wasm_artifact(path))
    return validations


def validate_wasm_artifact(path: Path) -> ArtifactValidation:
    if shutil.which("wasm-tools") is None:
        return ArtifactValidation(
            path=str(path),
            kind="wasm",
            status="unavailable",
            stderr="wasm-tools is not available in PATH",
        )
    completed = subprocess.run(
        ("wasm-tools", "validate", str(path)),
        capture_output=True,
        check=False,
        text=True,
    )
    return ArtifactValidation(
        path=str(path),
        kind="wasm",
        status="success" if completed.returncode == 0 else "error",
        stderr=normalize_text(completed.stderr),
    )


def format_target_check_text(check: TargetCheck) -> str:
    lines = [f"Target check: {check.status}"]
    if check.reason:
        lines.append(f"Reason: {check.reason}")
    lines.append("")
    lines.append(format_comparison_text(check.comparison))
    lines.extend(["", "Solang target validations:"])
    if not check.validations:
        lines.append("- none")
    for validation in check.validations:
        lines.append(f"- {validation.kind}: {validation.status} {validation.path}")
        if validation.stderr:
            lines.append(f"  stderr: {validation.stderr.splitlines()[0]}")
    return "\n".join(lines)


def format_target_check_json(check: TargetCheck) -> str:
    return json.dumps(check.to_json(), indent=2, sort_keys=True)
