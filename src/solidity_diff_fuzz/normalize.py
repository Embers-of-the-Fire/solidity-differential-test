import re

from .models import DiagnosticKind, OutcomeKind

ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def strip_ansi(text: str) -> str:
    return ANSI_ESCAPE.sub("", text)


def normalize_text(text: str) -> str:
    return "\n".join(line.rstrip() for line in strip_ansi(text).splitlines()).strip()


def classify_outcome(
    exit_code: int | None, stderr: str
) -> tuple[OutcomeKind, DiagnosticKind]:
    normalized = normalize_text(stderr).lower()
    if exit_code is None:
        return (OutcomeKind.TIMEOUT, DiagnosticKind.UNKNOWN)
    if any(marker in normalized for marker in _internal_error_markers()):
        return (OutcomeKind.CRASH, DiagnosticKind.INTERNAL_ERROR)
    if exit_code == 0:
        return (OutcomeKind.SUCCESS, DiagnosticKind.NONE)
    if "parser" in normalized or "syntax error" in normalized:
        return (OutcomeKind.DIAGNOSTIC, DiagnosticKind.PARSER)
    if "undeclared" in normalized or "not found" in normalized:
        return (OutcomeKind.DIAGNOSTIC, DiagnosticKind.RESOLUTION)
    if "type error" in normalized or "implicitly convertible" in normalized:
        return (OutcomeKind.DIAGNOSTIC, DiagnosticKind.TYPE)
    if "not supported" in normalized or "unsupported" in normalized:
        return (OutcomeKind.DIAGNOSTIC, DiagnosticKind.UNSUPPORTED)
    if "codegen" in normalized or "emit" in normalized:
        return (OutcomeKind.DIAGNOSTIC, DiagnosticKind.CODEGEN)
    return (OutcomeKind.DIAGNOSTIC, DiagnosticKind.UNKNOWN)


def _internal_error_markers() -> tuple[str, ...]:
    return (
        "internal compiler error",
        "panicked at",
        "stack backtrace",
        "assertion failed",
        "segmentation fault",
        "thread '",
    )
