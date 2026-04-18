from __future__ import annotations

import json

from solidity_diff_fuzz.corpus import (
    load_existing_source_digests,
    load_known_signatures,
    source_digest,
)


def test_load_existing_source_digests_deduplicates_identical_sources(tmp_path) -> None:
    source = "contract Demo {}\n"
    (tmp_path / "first.sol").write_text(source, encoding="utf-8")
    (tmp_path / "second.sol").write_text(source, encoding="utf-8")

    digests = load_existing_source_digests(tmp_path)

    assert digests == {source_digest(source)}


def test_load_known_signatures_reads_existing_records(tmp_path) -> None:
    (tmp_path / "first.json").write_text(
        json.dumps({"signature": "crash.solang.target-not-implemented"}),
        encoding="utf-8",
    )
    (tmp_path / "second.json").write_text(
        json.dumps({"signature": "diagnostic.type.none"}),
        encoding="utf-8",
    )

    signatures = load_known_signatures(tmp_path)

    assert signatures == {
        "crash.solang.target-not-implemented",
        "diagnostic.type.none",
    }
