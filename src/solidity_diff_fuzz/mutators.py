from __future__ import annotations

import random

from .generator import (
    FUNCTION_TEMPLATES,
    INT_TYPES,
    OPERATORS,
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
        _mutate_literals,
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
    spec.state_templates[index] = rng.choice(STATE_TEMPLATES)
    spec.mutation_history.append("state-snippet")


def _swap_function_snippet(spec: ProgramSpec, rng: random.Random) -> None:
    if not spec.function_templates:
        return
    index = rng.randrange(len(spec.function_templates))
    spec.function_templates[index] = rng.choice(FUNCTION_TEMPLATES)
    spec.mutation_history.append("function-snippet")


def _mutate_literals(spec: ProgramSpec, rng: random.Random) -> None:
    spec.context["literal_a"] = rng.randint(0, 255)
    spec.context["literal_b"] = rng.randint(1, 255)
    spec.mutation_history.append("literals")
