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
SCALAR_STATE_TEMPLATE = "snippets/state/scalar_state.sol.j2"
FUNCTION_TEMPLATES = [
    "snippets/functions/compound_assignment_probe.sol.j2",
    "snippets/functions/complex_struct_array_compound_assignment_probe.sol.j2",
    "snippets/functions/tuple_struct_storage_swap_probe.sol.j2",
    "snippets/functions/short_circuit_probe.sol.j2",
    "snippets/functions/pure_math_probe.sol.j2",
    "snippets/functions/fixed_array_probe.sol.j2",
    "snippets/functions/struct_roundtrip_probe.sol.j2",
    "snippets/functions/modifier_state_gate_probe.sol.j2",
    "snippets/functions/nested_loop_probe.sol.j2",
    "snippets/functions/storage_update_probe.sol.j2",
    "snippets/functions/tuple_probe.sol.j2",
    "snippets/functions/bytes_hash_probe.sol.j2",
    "snippets/functions/abi_encode_internal_fn_var_probe.sol.j2",
    "snippets/functions/abi_encode_internal_fn_packed_probe.sol.j2",
    "snippets/functions/abi_encode_rational_probe.sol.j2",
    "snippets/functions/state_initializer_external_call_probe.sol.j2",
]
INT_TYPES = ["uint8", "uint16", "uint32", "uint64", "uint128", "uint256"]
OPERATORS = ["+", "-", "^", "|", "&"]
COMPARE_OPERATORS = [">", ">=", "!="]
ENCODE_MODES = ["abi.encode", "abi.encodePacked"]
RATIONAL_LITERALS = ["24.24", "7.5", "0.125"]


def _contract_name(index: int) -> str:
    return f"FuzzCase{index:04d}"


def make_program_spec(rng: random.Random, case_index: int) -> ProgramSpec:
    extra_state_templates = [
        template for template in STATE_TEMPLATES if template != SCALAR_STATE_TEMPLATE
    ]
    state_templates = [SCALAR_STATE_TEMPLATE]
    state_templates.extend(
        rng.sample(extra_state_templates, k=rng.randint(0, len(extra_state_templates)))
    )
    function_templates = rng.sample(FUNCTION_TEMPLATES, k=rng.randint(2, 4))
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
        "secondary_helper_name": f"helper2_{case_index}",
        "modifier_name": f"bump_{case_index}",
        "struct_name": f"Pair{case_index}",
        "seed_method_name": f"seed_{case_index}",
        "int_type": int_type,
        "alt_int_type": rng.choice([kind for kind in INT_TYPES if kind != int_type]),
        "operator": rng.choice(OPERATORS),
        "compare_operator": rng.choice(COMPARE_OPERATORS),
        "encode_mode": rng.choice(ENCODE_MODES),
        "rational_literal": rng.choice(RATIONAL_LITERALS),
        "literal_a": rng.randint(0, 17),
        "literal_b": rng.randint(1, 17),
        "loop_bound": rng.randint(2, 5),
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
