from __future__ import annotations

import random
from pathlib import Path

from solidity_diff_fuzz.generator import make_program_spec, render_case
from solidity_diff_fuzz.template_loader import build_environment


def test_render_case_contains_contract_name(tmp_path: Path) -> None:
    environment = build_environment(Path(__file__).resolve().parents[1])
    spec = make_program_spec(random.Random(0), 7)
    case = render_case(environment, spec, tmp_path, "demo")
    assert spec.context["contract_name"] in case.source
    assert case.source_path.exists()
