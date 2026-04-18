from __future__ import annotations

import random
from pathlib import Path

from solidity_diff_fuzz.generator import make_program_spec, render_case
from solidity_diff_fuzz.models import ProgramSpec
from solidity_diff_fuzz.template_loader import build_environment


def test_render_case_contains_contract_name(tmp_path: Path) -> None:
    environment = build_environment(Path(__file__).resolve().parents[1])
    spec = make_program_spec(random.Random(0), 7)
    case = render_case(environment, spec, tmp_path, "demo")
    assert spec.context["contract_name"] in case.source
    assert case.source_path.exists()


def test_render_case_supports_complex_struct_array_probe(tmp_path: Path) -> None:
    environment = build_environment(Path(__file__).resolve().parents[1])
    spec = ProgramSpec(
        base_template="contracts/base.sol.j2",
        state_templates=["snippets/state/scalar_state.sol.j2"],
        function_templates=[
            "snippets/functions/complex_struct_array_compound_assignment_probe.sol.j2"
        ],
        context={
            "pragma": "^0.8.20",
            "contract_name": "ComplexProbe",
            "state_var_name": "value_0",
            "secondary_state_var_name": "flag_0",
            "mapping_name": "mapping_0",
            "array_name": "items_0",
            "probe_name": "probe_0",
            "helper_name": "helper_0",
            "secondary_helper_name": "helper2_0",
            "modifier_name": "bump_0",
            "struct_name": "Pair0",
            "seed_method_name": "seed_0",
            "int_type": "uint8",
            "alt_int_type": "uint16",
            "operator": "+",
            "compare_operator": ">",
            "encode_mode": "abi.encode",
            "rational_literal": "7.5",
            "literal_a": 1,
            "literal_b": 2,
            "loop_bound": 3,
        },
    )
    case = render_case(environment, spec, tmp_path, "complex")
    assert "struct Pair0Complex" in case.source
    assert "complex_value_0.items[0] += c;" in case.source


def test_render_case_supports_tuple_struct_storage_swap_probe(tmp_path: Path) -> None:
    environment = build_environment(Path(__file__).resolve().parents[1])
    spec = ProgramSpec(
        base_template="contracts/base.sol.j2",
        state_templates=["snippets/state/scalar_state.sol.j2"],
        function_templates=[
            "snippets/functions/tuple_struct_storage_swap_probe.sol.j2"
        ],
        context={
            "pragma": "^0.8.20",
            "contract_name": "TupleSwapProbe",
            "state_var_name": "value_0",
            "secondary_state_var_name": "flag_0",
            "mapping_name": "mapping_0",
            "array_name": "items_0",
            "probe_name": "probe_0",
            "helper_name": "helper_0",
            "secondary_helper_name": "helper2_0",
            "modifier_name": "bump_0",
            "struct_name": "Pair0",
            "seed_method_name": "seed_0",
            "int_type": "uint8",
            "alt_int_type": "uint16",
            "operator": "+",
            "compare_operator": ">",
            "encode_mode": "abi.encode",
            "rational_literal": "7.5",
            "literal_a": 1,
            "literal_b": 2,
            "loop_bound": 3,
        },
    )
    case = render_case(environment, spec, tmp_path, "tuple-swap")
    assert "struct Pair0Tuple" in case.source
    assert "(tuple_value_0.items[0], tuple_value_0.items[1]) = (" in case.source
