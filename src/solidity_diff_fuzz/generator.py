from __future__ import annotations

import random
from dataclasses import replace
from pathlib import Path

from .models import ProgramSpec, RenderedCase
from .template_loader import render_template

BASE_TEMPLATE = "contracts/base.sol.j2"
STATE_TEMPLATES = [
    "snippets/state/scalar_state.sol.j2",
    "snippets/state/mapping_state.sol.j2",
    "snippets/state/array_state.sol.j2",
]
FUNCTION_TEMPLATES = [
    "snippets/functions/pure_math_probe.sol.j2",
    "snippets/functions/storage_update_probe.sol.j2",
    "snippets/functions/tuple_probe.sol.j2",
    "snippets/functions/bytes_hash_probe.sol.j2",
]
INT_TYPES = ["uint8", "uint16", "uint32", "uint64", "uint128", "uint256"]
OPERATORS = ["+", "-", "^", "|", "&"]


def _contract_name(index: int) -> str:
    return f"FuzzCase{index:04d}"


def make_program_spec(rng: random.Random, case_index: int) -> ProgramSpec:
    state_templates = rng.sample(STATE_TEMPLATES, k=rng.randint(1, 2))
    function_templates = rng.sample(FUNCTION_TEMPLATES, k=rng.randint(1, 3))
    int_type = rng.choice(INT_TYPES)
    context = {
        "pragma": "^0.8.20",
        "contract_name": _contract_name(case_index),
        "state_var_name": f"value_{case_index}",
        "secondary_state_var_name": f"flag_{case_index}",
        "mapping_name": f"mapping_{case_index}",
        "array_name": f"items_{case_index}",
        "probe_name": f"probe_{case_index}",
        "helper_name": f"helper_{case_index}",
        "int_type": int_type,
        "alt_int_type": rng.choice([kind for kind in INT_TYPES if kind != int_type]),
        "operator": rng.choice(OPERATORS),
        "literal_a": rng.randint(0, 17),
        "literal_b": rng.randint(1, 17),
    }
    return ProgramSpec(
        base_template=BASE_TEMPLATE,
        state_templates=state_templates,
        function_templates=function_templates,
        context=context,
    )


def render_case(
    environment, spec: ProgramSpec, queue_dir: Path, case_id: str
) -> RenderedCase:
    source = render_template(
        environment,
        spec.base_template,
        state_templates=spec.state_templates,
        function_templates=spec.function_templates,
        **spec.context,
    )
    source_path = queue_dir / f"{case_id}.sol"
    source_path.write_text(source, encoding="utf-8")
    return RenderedCase(
        case_id=case_id, spec=spec, source=source, source_path=source_path
    )


def clone_spec(spec: ProgramSpec) -> ProgramSpec:
    return replace(
        spec,
        state_templates=list(spec.state_templates),
        function_templates=list(spec.function_templates),
        context=dict(spec.context),
        mutation_history=list(spec.mutation_history),
    )
