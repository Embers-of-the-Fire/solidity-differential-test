from __future__ import annotations

from .models import CompilerResult, MismatchKind, MismatchRecord, RenderedCase


def compare_results(
    case: RenderedCase, solc: CompilerResult, solang: CompilerResult
) -> MismatchRecord | None:
    if solc.outcome.value == "crash" or solang.outcome.value == "crash":
        culprit = "solc" if solc.outcome.value == "crash" else "solang"
        return _record(
            case,
            solc,
            solang,
            MismatchKind.CRASH,
            f"crash.{culprit}",
            f"Compiler crash detected in {culprit}",
        )
    if solc.outcome != solang.outcome:
        return _record(
            case,
            solc,
            solang,
            MismatchKind.ACCEPTANCE,
            f"acceptance.{solc.outcome.value}.{solang.outcome.value}",
            (
                "Outcome mismatch: "
                f"solc={solc.outcome.value}, solang={solang.outcome.value}"
            ),
        )
    if (
        solc.outcome.value == "diagnostic"
        and solc.diagnostic_kind != solang.diagnostic_kind
    ):
        return _record(
            case,
            solc,
            solang,
            MismatchKind.DIAGNOSTIC,
            f"diagnostic.{solc.diagnostic_kind.value}.{solang.diagnostic_kind.value}",
            "Diagnostic classes differ",
        )
    return None


def _record(
    case: RenderedCase,
    solc: CompilerResult,
    solang: CompilerResult,
    kind: MismatchKind,
    signature: str,
    summary: str,
) -> MismatchRecord:
    return MismatchRecord(
        case_id=case.case_id,
        kind=kind,
        signature=signature,
        summary=summary,
        source_path=str(case.source_path),
        source=case.source,
        spec=case.spec.to_json(),
        solc=solc.to_json(),
        solang=solang.to_json(),
    )
