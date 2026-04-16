from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import CampaignConfig
from .models import CompilerName, CompilerResult
from .normalize import classify_outcome, normalize_text


@dataclass(slots=True)
class RunOutput:
    returncode: int | None
    stdout: str
    stderr: str


def ensure_compilers_available() -> None:
    for tool in ("solc", "solang"):
        if shutil.which(tool) is None:
            msg = f"{tool} is not available in PATH"
            raise RuntimeError(msg)


def compile_with_solc(
    source_path: Path, config: CampaignConfig, work_dir: Path
) -> CompilerResult:
    command = ("solc", "--bin", str(source_path))
    completed = _run(command, config.timeout_seconds, work_dir)
    outcome, diagnostic = classify_outcome(completed.returncode, completed.stderr)
    return CompilerResult(
        compiler=CompilerName.SOLC,
        command=command,
        outcome=outcome,
        diagnostic_kind=diagnostic,
        exit_code=completed.returncode,
        stdout=normalize_text(completed.stdout),
        stderr=normalize_text(completed.stderr),
    )


def compile_with_solang(
    source_path: Path, config: CampaignConfig, work_dir: Path
) -> CompilerResult:
    artifact_dir = work_dir / "solang-artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    command = (
        "solang",
        "compile",
        str(source_path),
        "--target",
        config.solang_target,
        "--output",
        str(artifact_dir),
    )
    completed = _run(command, config.timeout_seconds, work_dir)
    outcome, diagnostic = classify_outcome(completed.returncode, completed.stderr)
    return CompilerResult(
        compiler=CompilerName.SOLANG,
        command=command,
        outcome=outcome,
        diagnostic_kind=diagnostic,
        exit_code=completed.returncode,
        stdout=normalize_text(completed.stdout),
        stderr=normalize_text(completed.stderr),
        artifact_paths=tuple(str(path) for path in sorted(artifact_dir.glob("*"))),
    )


def _run(command: tuple[str, ...], timeout_seconds: int, work_dir: Path) -> RunOutput:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            cwd=work_dir,
            text=True,
            timeout=timeout_seconds,
        )
        return RunOutput(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout if isinstance(error.stdout, str) else ""
        stderr = error.stderr if isinstance(error.stderr, str) else ""
        return RunOutput(
            returncode=None,
            stdout=stdout,
            stderr=f"{stderr}\nTimed out",
        )
