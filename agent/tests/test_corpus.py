"""Unit tests for the corpus: admission rule, dedup, energy, parent selection."""

import json
import random

from agent.corpus import (
    ENERGY_DECAY,
    ENERGY_FLOOR,
    ENERGY_INIT,
    Corpus,
    spec_id,
)


def spec(source="contract c {}", name="x"):
    return {"name": name, "solidity": source, "contract": "c", "steps": []}


def div_report(kind="RETURN_MISMATCH"):
    return {
        "verdict": "DIVERGENCE",
        "divergences": [{"kind": kind, "step": 0, "detail": "d"}],
    }


PASS_REPORT = {"verdict": "PASS", "divergences": []}
ERROR_REPORT = {"verdict": "ERROR", "divergences": [], "error": "boom"}


def admit(corpus, **kw):
    defaults = {
        "spec": spec(),
        "report": div_report(),
        "seed_id": "s1",
        "parent_id": None,
        "origin": "generated",
        "category": "bug_candidate",
        "known_finding": False,
    }
    return corpus.admit(**(defaults | kw))


def test_admission_rule_per_outcome_class(tmp_path):
    corpus = Corpus(tmp_path / "corpus.jsonl")
    # PASS is never admitted
    assert admit(corpus, report=PASS_REPORT, category="pass") is None
    # DIVERGENCE with an unknown finding fingerprint is admitted
    first = admit(corpus)
    assert first is not None and first["admitted_by"] == "divergence"
    # DIVERGENCE that is already a known finding and whose kind combo has
    # been seen in this seed is not admitted
    assert admit(corpus, spec=spec(name="y"), known_finding=True) is None
    # ... but a novel kind combo is admitted even for a known-finding/artifact
    artifact = admit(
        corpus,
        spec=spec(name="z"),
        report=div_report("STORAGE_COUNT_MISMATCH"),
        category="oracle_artifact",
        known_finding=True,
    )
    assert artifact is not None and artifact["admitted_by"] == "novel_kinds"
    # seed initial specs are always admitted
    seeded = admit(corpus, spec=spec(name="seed0"), report=PASS_REPORT, origin="seed")
    assert seeded is not None and seeded["admitted_by"] == "seed"


def test_admission_dedup_is_content_derived(tmp_path):
    corpus = Corpus(tmp_path / "corpus.jsonl")
    assert admit(corpus) is not None
    # identical spec (meta excluded) -> no-op
    again = dict(spec(), meta={"parent_id": "whatever", "origin": "generated"})
    assert admit(corpus, spec=again) is None
    assert len(corpus.entries()) == 1
    # meta does not affect the id
    assert spec_id(spec()) == spec_id(again)


def test_missing_file_loads_empty(tmp_path):
    corpus = Corpus(tmp_path / "corpus.jsonl")
    assert corpus.entries() == []
    assert corpus.select_parent("s1", random.Random(0)) is None


def test_energy_updates_and_floor(tmp_path):
    corpus = Corpus(tmp_path / "corpus.jsonl")
    parent = admit(corpus)
    assert parent is not None
    assert parent["energy"] == ENERGY_INIT
    corpus.record_offspring(parent["id"], "divergent")
    assert parent["energy"] == ENERGY_INIT + 1.0
    assert parent["offspring"] == {"runs": 1, "divergent": 1, "novel": 0, "invalid": 0}
    corpus.record_offspring(parent["id"], "novel")
    assert parent["energy"] == ENERGY_INIT + 3.0
    for _ in range(50):
        corpus.record_offspring(parent["id"], "invalid")
    assert parent["energy"] == ENERGY_FLOOR
    corpus.record_offspring(parent["id"], "duplicate")
    assert parent["energy"] == ENERGY_FLOOR
    corpus.record_offspring("nonexistent", "divergent")  # no-op, no crash


def test_decay_respects_floor(tmp_path):
    corpus = Corpus(tmp_path / "corpus.jsonl")
    parent = admit(corpus)
    assert parent is not None
    corpus.decay()
    assert parent["energy"] == ENERGY_INIT * ENERGY_DECAY
    for _ in range(200):
        corpus.decay()
    assert parent["energy"] == ENERGY_FLOOR


def test_classify_offspring(tmp_path):
    corpus = Corpus(tmp_path / "corpus.jsonl")
    parent = admit(corpus)
    assert parent is not None
    # novel kind combo for the parent's seed
    assert (
        corpus.classify_offspring(
            parent=parent,
            spec=spec(name="a"),
            report=div_report("NEW_KIND"),
            category="bug_candidate",
        )
        == "novel"
    )
    # same combo as the parent -> divergent
    assert (
        corpus.classify_offspring(
            parent=parent,
            spec=spec(name="b"),
            report=div_report(),
            category="bug_candidate",
        )
        == "divergent"
    )
    assert (
        corpus.classify_offspring(
            parent=parent, spec=spec(name="c"), report=ERROR_REPORT, category="error"
        )
        == "invalid"
    )
    assert (
        corpus.classify_offspring(
            parent=parent, spec=spec(name="d"), report=PASS_REPORT, category="pass"
        )
        == "pass"
    )
    # spec already in the corpus -> duplicate
    assert (
        corpus.classify_offspring(
            parent=parent, spec=spec(), report=div_report(), category="bug_candidate"
        )
        == "duplicate"
    )


def test_parent_selection_converges_to_high_yield(tmp_path):
    corpus = Corpus(tmp_path / "corpus.jsonl")
    strong = admit(corpus, spec=spec(name="strong"))
    weak = admit(corpus, spec=spec(name="weak"), report=div_report("K2"))
    other_seed = admit(corpus, spec=spec(name="other"), seed_id="s2")
    assert strong is not None and weak is not None and other_seed is not None
    for _ in range(5):
        corpus.record_offspring(strong["id"], "novel")
    picks = [corpus.select_parent("s1", random.Random(i)) for i in range(200)]
    pick_ids = [p["id"] for p in picks if p is not None]
    assert len(pick_ids) == 200
    assert pick_ids.count(strong["id"]) > 180
    assert weak["id"] in pick_ids  # roulette, not argmax
    assert other_seed["id"] not in pick_ids  # seed partitioning


def test_save_reload_roundtrip(tmp_path):
    path = tmp_path / "corpus.jsonl"
    corpus = Corpus(path)
    entry = admit(corpus)
    assert entry is not None
    corpus.record_offspring(entry["id"], "novel")
    corpus.save()
    reloaded = Corpus(path)
    assert len(reloaded.entries()) == 1
    e = reloaded.entries()[0]
    assert e["id"] == entry["id"]
    assert e["energy"] == ENERGY_INIT + 2.0
    assert e["offspring"]["novel"] == 1
    assert e["origin"] == "generated"
    assert e["parent_id"] is None
    assert "meta" not in e["spec"]
    json.loads(path.read_text().strip())  # valid JSONL
