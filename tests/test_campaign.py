from __future__ import annotations

from pathlib import Path

from solidity_diff_fuzz.campaign import run_campaign
from solidity_diff_fuzz.config import CampaignConfig
from solidity_diff_fuzz.models import (
    CompilerName,
    CompilerResult,
    DiagnosticKind,
    OutcomeKind,
    ProgramSpec,
    RenderedCase,
)


def test_campaign_skips_known_signatures_and_duplicate_sources(
    tmp_path: Path, monkeypatch
) -> None:
    config = CampaignConfig(root_dir=tmp_path, artifact_dir=tmp_path / "artifacts")
    config.crashes_dir.mkdir(parents=True, exist_ok=True)
    (config.crashes_dir / "known.json").write_text(
        '{"signature": "crash.solang.target-not-implemented"}', encoding="utf-8"
    )

    queue_calls: list[str] = []
    solc_calls: list[str] = []
    solang_calls: list[str] = []

    monkeypatch.setattr(
        "solidity_diff_fuzz.campaign.ensure_compilers_available", lambda: None
    )
    monkeypatch.setattr(
        "solidity_diff_fuzz.campaign.build_environment", lambda root: object()
    )

    def fake_make_program_spec(rng, case_index: int) -> ProgramSpec:
        return ProgramSpec(
            base_template="contracts/base.sol.j2",
            state_templates=[],
            function_templates=[],
            context={"contract_name": f"Demo{case_index}"},
        )

    def fake_mutate_spec(spec: ProgramSpec, rng) -> ProgramSpec:
        return spec

    def fake_render_case(
        environment, spec: ProgramSpec, queue_dir: Path, case_id: str
    ) -> RenderedCase:
        queue_calls.append(case_id)
        source = "contract Same {}\n"
        source_path = queue_dir / f"{case_id}.sol"
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_text(source, encoding="utf-8")
        return RenderedCase(
            case_id=case_id,
            spec=spec,
            source=source,
            source_path=source_path,
        )

    def fake_solc(path: Path, cfg: CampaignConfig, work_dir: Path) -> CompilerResult:
        solc_calls.append(path.name)
        return CompilerResult(
            compiler=CompilerName.SOLC,
            command=("solc",),
            outcome=OutcomeKind.SUCCESS,
            diagnostic_kind=DiagnosticKind.NONE,
            exit_code=0,
            stdout="",
            stderr="",
        )

    def fake_solang(path: Path, cfg: CampaignConfig, work_dir: Path) -> CompilerResult:
        solang_calls.append(path.name)
        return CompilerResult(
            compiler=CompilerName.SOLANG,
            command=("solang",),
            outcome=OutcomeKind.CRASH,
            diagnostic_kind=DiagnosticKind.INTERNAL_ERROR,
            exit_code=101,
            stdout="",
            stderr="not implemented: target not implemented",
        )

    monkeypatch.setattr(
        "solidity_diff_fuzz.campaign.make_program_spec", fake_make_program_spec
    )
    monkeypatch.setattr("solidity_diff_fuzz.campaign.mutate_spec", fake_mutate_spec)
    monkeypatch.setattr("solidity_diff_fuzz.campaign.render_case", fake_render_case)
    monkeypatch.setattr("solidity_diff_fuzz.campaign.compile_with_solc", fake_solc)
    monkeypatch.setattr("solidity_diff_fuzz.campaign.compile_with_solang", fake_solang)

    findings = run_campaign(config, iterations=1, mutate_rounds=2)

    assert queue_calls == ["case-00000-m0", "case-00000-m1"]
    assert solc_calls == ["case-00000-m0.sol"]
    assert solang_calls == ["case-00000-m0.sol"]
    assert findings == []
