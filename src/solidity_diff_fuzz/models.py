from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class CompilerName(StrEnum):
    SOLC = "solc"
    SOLANG = "solang"


class OutcomeKind(StrEnum):
    SUCCESS = "success"
    DIAGNOSTIC = "diagnostic"
    CRASH = "crash"
    TIMEOUT = "timeout"


class DiagnosticKind(StrEnum):
    NONE = "none"
    PARSER = "parser"
    RESOLUTION = "resolution"
    TYPE = "type"
    UNSUPPORTED = "unsupported"
    CODEGEN = "codegen"
    INTERNAL_ERROR = "internal-error"
    UNKNOWN = "unknown"


class MismatchKind(StrEnum):
    NONE = "none"
    ACCEPTANCE = "acceptance-mismatch"
    CRASH = "crash"
    DIAGNOSTIC = "diagnostic-class-mismatch"


@dataclass(slots=True)
class CompilerResult:
    compiler: CompilerName
    command: tuple[str, ...]
    outcome: OutcomeKind
    diagnostic_kind: DiagnosticKind
    exit_code: int | None
    stdout: str
    stderr: str
    artifact_paths: tuple[str, ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {
            "compiler": self.compiler.value,
            "command": list(self.command),
            "outcome": self.outcome.value,
            "diagnostic_kind": self.diagnostic_kind.value,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "artifact_paths": list(self.artifact_paths),
        }


@dataclass(slots=True)
class ProgramSpec:
    base_template: str
    state_templates: list[str]
    function_templates: list[str]
    context: dict[str, Any]
    mutation_history: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "base_template": self.base_template,
            "state_templates": self.state_templates,
            "function_templates": self.function_templates,
            "context": self.context,
            "mutation_history": self.mutation_history,
        }


@dataclass(slots=True)
class RenderedCase:
    case_id: str
    spec: ProgramSpec
    source: str
    source_path: Path


@dataclass(slots=True)
class MismatchRecord:
    case_id: str
    kind: MismatchKind
    signature: str
    summary: str
    source_path: str
    source: str
    spec: dict[str, Any]
    solc: dict[str, Any]
    solang: dict[str, Any]
