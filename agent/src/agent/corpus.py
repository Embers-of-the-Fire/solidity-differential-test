"""Corpus of admitted test inputs with lineage and energy-based selection.

Every executed spec may be admitted into `corpus.jsonl` (append-only style,
compaction-on-load: volumes are small, so updates rewrite the whole file).
Admission is the explicit "interestingness" decision; energy drives
fitness-proportional parent selection within a seed partition. Mutation
operators themselves are plan 04 — this module only manages the corpus.

Entry schema:

    id          sha1 of the canonical spec json (without "meta"), 16 hex
    ts          admission time
    seed        seed id (corpus is partitioned per seed; no cross-seed sharing)
    parent_id   corpus id of the parent, or null when generated from scratch
    origin      generated | mutated_llm | mutated_prog | seed
    spec        the spec dict (without "meta")
    outcome     {verdict, kinds, category} of the run that admitted it
    admitted_by divergence | novel_kinds | seed | unfiltered
    energy      selection weight (see constants below)
    offspring   {runs, divergent, novel, invalid}
"""

from __future__ import annotations

import hashlib
import json
import random
import time
from pathlib import Path
from typing import Any

from .executor import divergence_kinds

ENERGY_INIT = 1.0
ENERGY_DIVERGENT = 1.0
ENERGY_NOVEL = 2.0
ENERGY_INVALID = -0.1
ENERGY_FLOOR = 0.1
ENERGY_DECAY = 0.95


def spec_id(spec: dict[str, Any]) -> str:
    """Content-derived id: sha1 of canonical spec json, ignoring "meta"."""
    body = {k: v for k, v in spec.items() if k != "meta"}
    canonical = json.dumps(body, sort_keys=True)
    return hashlib.sha1(canonical.encode()).hexdigest()[:16]


class Corpus:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._entries: list[dict[str, Any]] = []
        if self.path.exists():
            self._entries = [
                json.loads(line)
                for line in self.path.read_text().strip().splitlines()
                if line.strip()
            ]

    # --- queries ------------------------------------------------------------

    def entries(self, seed_id: str | None = None) -> list[dict[str, Any]]:
        if seed_id is None:
            return list(self._entries)
        return [e for e in self._entries if e["seed"] == seed_id]

    def _by_id(self, entry_id: str) -> dict[str, Any] | None:
        for e in self._entries:
            if e["id"] == entry_id:
                return e
        return None

    def _kind_combos(self, seed_id: str) -> set[tuple[str, ...]]:
        return {
            tuple(e["outcome"]["kinds"])
            for e in self._entries
            if e["seed"] == seed_id and e["outcome"]["kinds"]
        }

    # --- admission ----------------------------------------------------------

    def admit(
        self,
        *,
        spec: dict[str, Any],
        report: dict[str, Any],
        seed_id: str,
        parent_id: str | None,
        origin: str,
        category: str,
        known_finding: bool,
        admit_all: bool = False,
    ) -> dict[str, Any] | None:
        """Admit an executed spec per the v1 outcome-based rule.

        Returns the new entry, or None when the spec is not admitted
        (PASS runs, known findings, already-seen kind combos, duplicates).
        With admit_all=True every unseen executed spec is admitted as
        "unfiltered" (the evaluation harness's random-restart control).
        """
        entry_id = spec_id(spec)
        if self._by_id(entry_id) is not None:
            return None  # content-derived id: re-admission is a no-op
        kinds = sorted(divergence_kinds(report))
        admitted_by = None
        if admit_all:
            admitted_by = "unfiltered"
        elif origin == "seed":
            admitted_by = "seed"
        elif report.get("verdict") == "DIVERGENCE" and not known_finding:
            admitted_by = "divergence"
        elif kinds and tuple(kinds) not in self._kind_combos(seed_id):
            admitted_by = "novel_kinds"
        if admitted_by is None:
            return None
        entry = {
            "id": entry_id,
            "ts": time.time(),
            "seed": seed_id,
            "parent_id": parent_id,
            "origin": origin,
            "spec": {k: v for k, v in spec.items() if k != "meta"},
            "outcome": {
                "verdict": report.get("verdict"),
                "kinds": kinds,
                "category": category,
            },
            "admitted_by": admitted_by,
            "energy": ENERGY_INIT,
            "offspring": {"runs": 0, "divergent": 0, "novel": 0, "invalid": 0},
        }
        self._entries.append(entry)
        return entry

    # --- offspring feedback / energy ----------------------------------------

    def classify_offspring(
        self,
        *,
        parent: dict[str, Any],
        spec: dict[str, Any],
        report: dict[str, Any],
        category: str,
    ) -> str:
        """Classify a child's outcome for the parent's energy update."""
        if self._by_id(spec_id(spec)) is not None:
            return "duplicate"
        if report.get("verdict") == "ERROR" or category == "invalid_probe":
            return "invalid"
        kinds = sorted(divergence_kinds(report))
        if kinds:
            if tuple(kinds) not in self._kind_combos(parent["seed"]):
                return "novel"
            return "divergent"
        return "pass"

    def record_offspring(self, parent_id: str, outcome: str) -> None:
        parent = self._by_id(parent_id)
        if parent is None:
            return
        parent["offspring"]["runs"] += 1
        if outcome in ("divergent", "novel", "invalid"):
            parent["offspring"][outcome] += 1
        delta = {
            "divergent": ENERGY_DIVERGENT,
            "novel": ENERGY_NOVEL,
            "invalid": ENERGY_INVALID,
            "duplicate": ENERGY_INVALID,
        }.get(outcome, 0.0)
        parent["energy"] = max(ENERGY_FLOOR, parent["energy"] + delta)

    def decay(self) -> None:
        """Mild per-round decay so early parents do not dominate forever."""
        for e in self._entries:
            e["energy"] = max(ENERGY_FLOOR, e["energy"] * ENERGY_DECAY)

    # --- parent selection ----------------------------------------------------

    def select_parent(self, seed_id: str, rng: random.Random) -> dict[str, Any] | None:
        """Fitness-proportional (roulette) selection within one seed."""
        entries = self.entries(seed_id)
        if not entries:
            return None
        return rng.choices(entries, weights=[e["energy"] for e in entries], k=1)[0]

    # --- persistence ----------------------------------------------------------

    def save(self) -> None:
        """Compaction-on-load: rewrite the whole file with updated energies."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w") as f:
            for e in self._entries:
                f.write(json.dumps(e) + "\n")
