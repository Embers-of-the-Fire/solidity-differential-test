"""Schema validation for the bug-derived seed corpus and --seeds-dir loading.

`agent/seeds_derived/` is the frozen, human-curated artifact of the offline
fetch -> distill -> curate pipeline (plan 06). It starts empty; every card
committed there must satisfy the Seed schema plus the distillation rules
(kebab-case id, cross-implementation `why`).
"""

import json
import re
from pathlib import Path

import pytest

from agent.seeds import Seed, load_seeds

SEEDS_DERIVED = Path(__file__).resolve().parents[1] / "seeds_derived"
KEBAB_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def derived_cards() -> list[Path]:
    if not SEEDS_DERIVED.is_dir():
        return []
    return sorted(SEEDS_DERIVED.glob("*.json"))


@pytest.mark.parametrize("path", derived_cards(), ids=lambda p: p.name or "none")
def test_derived_card_schema(path: Path):
    card = json.loads(path.read_text())
    seed = Seed.from_dict(card)  # raises on missing required keys
    assert seed.id == path.stem, "card id must match its filename"
    assert KEBAB_RE.match(seed.id), f"id {seed.id!r} must be kebab-case"
    assert seed.title.strip()
    assert "solc" in seed.why.lower() and "solang" in seed.why.lower(), (
        "why must state a cross-implementation divergence hypothesis"
    )
    assert seed.hints and all(isinstance(h, str) and h for h in seed.hints)
    source = card.get("source")
    assert isinstance(source, dict) and source.get("url"), (
        "derived cards must carry provenance (source.url)"
    )
    assert source.get("kind") in (
        "solang-issue",
        "solang-pr",
        "solang-changelog",
        "solc-bugs",
    )


def test_derived_ids_unique():
    ids = [p.stem for p in derived_cards()]
    assert len(ids) == len(set(ids))


def test_load_seeds_explicit_dir(tmp_path):
    (tmp_path / "foo.json").write_text(
        json.dumps(
            {"id": "foo", "title": "Foo", "why": "solc vs solang", "hints": ["x"]}
        )
    )
    seeds = load_seeds(tmp_path)
    assert [s.id for s in seeds] == ["foo"]
    assert seeds[0].hints == ["x"]


def test_load_seeds_explicit_dir_empty(tmp_path):
    with pytest.raises(RuntimeError, match="no seed cards"):
        load_seeds(tmp_path)


def test_load_seeds_missing_dir(tmp_path):
    with pytest.raises(RuntimeError, match="not found"):
        load_seeds(tmp_path / "nope")


def test_load_seeds_default_packaged():
    seeds = load_seeds()
    assert len(seeds) >= 10
    assert all(KEBAB_RE.match(s.id) for s in seeds)
