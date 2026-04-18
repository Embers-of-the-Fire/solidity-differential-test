from __future__ import annotations

import random

from .generator import (
    COMPARE_OPERATORS,
    ENCODE_MODES,
    FUNCTION_TEMPLATES,
    INT_TYPES,
    OPERATORS,
    RATIONAL_LITERALS,
    SCALAR_STATE_TEMPLATE,
    STATE_TEMPLATES,
    clone_spec,
)
from .models import ProgramSpec


def mutate_spec(spec: ProgramSpec, rng: random.Random) -> ProgramSpec:
    mutated = clone_spec(spec)
    mutators = [
        _mutate_operator,
        _mutate_integer_width,
        _swap_state_snippet,
        _swap_function_snippet,
        _append_function_snippet,
        _mutate_literals,
        _mutate_compare_operator,
        _mutate_encode_mode,
        _mutate_rational_literal,
    ]
    chosen = rng.choice(mutators)
    chosen(mutated, rng)
    return mutated


def _mutate_operator(spec: ProgramSpec, rng: random.Random) -> None:
    current = spec.context["operator"]
    spec.context["operator"] = rng.choice(
        [value for value in OPERATORS if value != current]
    )
    spec.mutation_history.append("operator")


def _mutate_integer_width(spec: ProgramSpec, rng: random.Random) -> None:
    current = spec.context["int_type"]
    updated = rng.choice([value for value in INT_TYPES if value != current])
    spec.context["int_type"] = updated
    spec.mutation_history.append("int-width")


def _swap_state_snippet(spec: ProgramSpec, rng: random.Random) -> None:
    if not spec.state_templates:
        return
    index = rng.randrange(len(spec.state_templates))
    if spec.state_templates[index] == SCALAR_STATE_TEMPLATE:
        return
    spec.state_templates[index] = rng.choice(STATE_TEMPLATES)
    spec.mutation_history.append("state-snippet")


def _swap_function_snippet(spec: ProgramSpec, rng: random.Random) -> None:
    if not spec.function_templates:
        return
    index = rng.randrange(len(spec.function_templates))
    spec.function_templates[index] = rng.choice(FUNCTION_TEMPLATES)
    spec.mutation_history.append("function-snippet")


def _append_function_snippet(spec: ProgramSpec, rng: random.Random) -> None:
    if len(spec.function_templates) >= 5:
        return
    spec.function_templates.append(rng.choice(FUNCTION_TEMPLATES))
    spec.mutation_history.append("function-append")


def _mutate_literals(spec: ProgramSpec, rng: random.Random) -> None:
    spec.context["literal_a"] = rng.randint(0, 255)
    spec.context["literal_b"] = rng.randint(1, 255)
    spec.context["loop_bound"] = rng.randint(2, 8)
    spec.mutation_history.append("literals")


def _mutate_compare_operator(spec: ProgramSpec, rng: random.Random) -> None:
    current = spec.context["compare_operator"]
    spec.context["compare_operator"] = rng.choice(
        [value for value in COMPARE_OPERATORS if value != current]
    )
    spec.mutation_history.append("compare-operator")


def _mutate_encode_mode(spec: ProgramSpec, rng: random.Random) -> None:
    current = spec.context["encode_mode"]
    spec.context["encode_mode"] = rng.choice(
        [value for value in ENCODE_MODES if value != current]
    )
    spec.mutation_history.append("encode-mode")


def _mutate_rational_literal(spec: ProgramSpec, rng: random.Random) -> None:
    current = spec.context["rational_literal"]
    spec.context["rational_literal"] = rng.choice(
        [value for value in RATIONAL_LITERALS if value != current]
    )
    spec.mutation_history.append("rational-literal")
