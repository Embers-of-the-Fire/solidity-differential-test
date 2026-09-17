"""Feature seed cards: suspected divergence areas for the generator.

Each card is a JSON document in `seeds/` describing one language area where
solc (EVM) and solang (Polkadot WASM) plausibly diverge. The loop samples
cards, hands them to the LLM as generation targets, and tracks coverage in
the findings store.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from importlib.resources import files
from typing import Any


@dataclass
class Seed:
    id: str
    title: str
    why: str
    hints: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Seed:
        return cls(
            id=d["id"],
            title=d["title"],
            why=d["why"],
            hints=list(d.get("hints", [])),
        )


def load_seeds() -> list[Seed]:
    seed_dir = files("agent") / "seeds"
    seeds = [
        Seed.from_dict(json.loads((seed_dir / name).read_text()))
        for name in sorted(str(n) for n in seed_dir.iterdir())
        if name.endswith(".json")
    ]
    if not seeds:
        raise RuntimeError("no seed cards found in agent/seeds/")
    return seeds


def pick_seed(
    seeds: list[Seed],
    stats: dict[str, dict[str, Any]],
    rng: random.Random,
    only: list[str] | None = None,
    resolved: set[str] | None = None,
) -> Seed:
    """Coverage-first sampling: least-probed seed wins; ties broken randomly.

    Seeds in `resolved` (all hypotheses confirmed/refuted) count double, so
    unresolved areas are preferred without ever hard-excluding resolved ones.
    """
    pool = [s for s in seeds if only is None or s.id in only]
    if not pool:
        raise ValueError(f"no seeds match filter {only}")
    rng.shuffle(pool)
    resolved = resolved or set()

    def weight(s: Seed) -> int:
        probes = stats.get(s.id, {}).get("probes", 0)
        return probes * 2 if s.id in resolved else probes

    return min(pool, key=weight)
