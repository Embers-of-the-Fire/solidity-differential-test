from __future__ import annotations

from pathlib import Path

from solidity_diff_fuzz.models import (
    CompilerName,
    CompilerResult,
    DiagnosticKind,
    MismatchKind,
    OutcomeKind,
    ProgramSpec,
    RenderedCase,
)
from solidity_diff_fuzz.oracle import compare_results


def test_acceptance_mismatch_is_reported(tmp_path: Path) -> None:
    case = RenderedCase(
        case_id="case-1",
        spec=ProgramSpec(
            base_template="contracts/base.sol.j2",
            state_templates=[],
            function_templates=[],
            context={"contract_name": "Demo"},
        ),
        source="contract Demo {}\n",
        source_path=tmp_path / "case-1.sol",
    )
    left = CompilerResult(
        compiler=CompilerName.SOLC,
        command=("solc",),
        outcome=OutcomeKind.SUCCESS,
        diagnostic_kind=DiagnosticKind.NONE,
        exit_code=0,
        stdout="",
        stderr="",
    )
    right = CompilerResult(
        compiler=CompilerName.SOLANG,
        command=("solang",),
        outcome=OutcomeKind.DIAGNOSTIC,
        diagnostic_kind=DiagnosticKind.PARSER,
        exit_code=1,
        stdout="",
        stderr="ParserError",
    )

    mismatch = compare_results(case, left, right)
    assert mismatch is not None
    assert mismatch.kind == MismatchKind.ACCEPTANCE


def test_dual_success_is_not_interesting(tmp_path: Path) -> None:
    case = RenderedCase(
        case_id="case-2",
        spec=ProgramSpec(
            base_template="contracts/base.sol.j2",
            state_templates=[],
            function_templates=[],
            context={"contract_name": "Demo"},
        ),
        source="contract Demo {}\n",
        source_path=tmp_path / "case-2.sol",
    )
    left = CompilerResult(
        compiler=CompilerName.SOLC,
        command=("solc",),
        outcome=OutcomeKind.SUCCESS,
        diagnostic_kind=DiagnosticKind.NONE,
        exit_code=0,
        stdout="",
        stderr="",
    )
    right = CompilerResult(
        compiler=CompilerName.SOLANG,
        command=("solang",),
        outcome=OutcomeKind.SUCCESS,
        diagnostic_kind=DiagnosticKind.NONE,
        exit_code=0,
        stdout="",
        stderr="",
    )

    assert compare_results(case, left, right) is None


def test_unsupported_gap_is_ignored(tmp_path: Path) -> None:
    case = RenderedCase(
        case_id="case-3",
        spec=ProgramSpec(
            base_template="contracts/base.sol.j2",
            state_templates=[],
            function_templates=[],
            context={"contract_name": "Demo"},
        ),
        source="contract Demo {}\n",
        source_path=tmp_path / "case-3.sol",
    )
    left = CompilerResult(
        compiler=CompilerName.SOLC,
        command=("solc",),
        outcome=OutcomeKind.SUCCESS,
        diagnostic_kind=DiagnosticKind.NONE,
        exit_code=0,
        stdout="",
        stderr="",
    )
    right = CompilerResult(
        compiler=CompilerName.SOLANG,
        command=("solang",),
        outcome=OutcomeKind.DIAGNOSTIC,
        diagnostic_kind=DiagnosticKind.UNSUPPORTED,
        exit_code=1,
        stdout="",
        stderr="unsupported",
    )

    assert compare_results(case, left, right) is None


def test_crash_signature_captures_message(tmp_path: Path) -> None:
    case = RenderedCase(
        case_id="case-4",
        spec=ProgramSpec(
            base_template="contracts/base.sol.j2",
            state_templates=[],
            function_templates=[],
            context={"contract_name": "Demo"},
        ),
        source="contract Demo {}\n",
        source_path=tmp_path / "case-4.sol",
    )
    left = CompilerResult(
        compiler=CompilerName.SOLC,
        command=("solc",),
        outcome=OutcomeKind.DIAGNOSTIC,
        diagnostic_kind=DiagnosticKind.UNKNOWN,
        exit_code=1,
        stdout="",
        stderr="diagnostic",
    )
    right = CompilerResult(
        compiler=CompilerName.SOLANG,
        command=("solang",),
        outcome=OutcomeKind.CRASH,
        diagnostic_kind=DiagnosticKind.INTERNAL_ERROR,
        exit_code=101,
        stdout="",
        stderr="internal error: entered unreachable code: This type cannot be encoded",
    )

    mismatch = compare_results(case, left, right)
    assert mismatch is not None
    assert (
        mismatch.signature
        == "crash.solang.entered-unreachable-code-this-type-cannot-be-encoded"
    )
