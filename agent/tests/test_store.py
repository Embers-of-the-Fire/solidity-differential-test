from agent.store import FindingStore, fingerprint


def spec(source="contract c {}", name="x"):
    return {"name": name, "solidity": source, "contract": "c", "steps": []}


SIG = "RETURN_MISMATCH|0|get|int≠int"
SIG2 = "EVENT_MISMATCH|0|emit|args"


def div_report(kind="RETURN_MISMATCH", detail="dry-run return values differ", sig=SIG):
    return {
        "verdict": "DIVERGENCE",
        "divergences": [{"kind": kind, "step": 0, "detail": detail, "signature": sig}],
        "earliest_divergence": {"point": 0, "signature": sig},
        "tool_versions": {"solc": "x"},
    }


TRIAGE = {
    "category": "bug_candidate",
    "confidence": "high",
    "rationale": "r",
    "blame": "solang",
    "summary": "s",
}


def test_add_finding_and_dedup(tmp_path):
    store = FindingStore(tmp_path)
    fid = store.add_finding(
        spec=spec(), report=div_report(), triage=TRIAGE, seed_id="s1"
    )
    assert fid is not None
    dup = store.add_finding(
        spec=spec(), report=div_report(), triage=TRIAGE, seed_id="s1"
    )
    assert dup is None
    assert len(store.findings()) == 1
    finding = store.get_finding(fid)
    assert finding is not None and finding["triage"]["blame"] == "solang"
    assert finding["earliest_signature"] == SIG
    assert finding["signatures"] == [SIG]
    report = store.report_for(fid)
    assert report is not None and report["verdict"] == "DIVERGENCE"


def test_same_signature_different_source_dedups(tmp_path):
    """T0.2/D2: the fingerprint is the signature set, not the source text."""
    store = FindingStore(tmp_path)
    fid = store.add_finding(
        spec=spec(
            source="contract c { function get() external returns (uint) { return 1; } }"
        ),
        report=div_report(),
        triage=TRIAGE,
        seed_id="s1",
    )
    assert fid is not None
    dup = store.add_finding(
        spec=spec(
            source="contract c { // different spelling\n function get() external returns (uint) { return 2; } }"
        ),
        report=div_report(),
        triage=TRIAGE,
        seed_id="s1",
    )
    assert dup is None
    assert len(store.findings()) == 1


def test_distinct_signatures_are_distinct_findings(tmp_path):
    store = FindingStore(tmp_path)
    a = store.add_finding(spec=spec(), report=div_report(), triage=TRIAGE, seed_id="s1")
    b = store.add_finding(
        spec=spec(),
        report=div_report(kind="EVENT_MISMATCH", sig=SIG2),
        triage=TRIAGE,
        seed_id="s1",
    )
    assert a is not None and b is not None and a != b
    assert store.known_signatures() == {SIG, SIG2}


def test_fingerprint_is_order_insensitive():
    assert fingerprint({"a", "b"}) == fingerprint({"b", "a"})
    assert fingerprint({"a", "b"}) != fingerprint({"a"})


def test_probes_and_seed_stats(tmp_path):
    store = FindingStore(tmp_path)
    for i in range(3):
        store.record_probe(
            spec=spec(name=f"p{i}"),
            report={"verdict": "PASS"},
            seed_id="s1",
            category="pass",
        )
    store.note_seed_result("s1", {"RETURN_MISMATCH"})
    store.note_seed_result("s1", set())
    recent = store.recent_probes(2)
    assert [p["name"] for p in recent] == ["p1", "p2"]
    assert store.seed_stats()["s1"]["probes"] == 2
    assert store.seed_stats()["s1"]["kinds_found"] == ["RETURN_MISMATCH"]


def test_empty_store(tmp_path):
    store = FindingStore(tmp_path)
    assert store.findings() == []
    assert store.recent_probes() == []
    assert store.known_fingerprints() == set()


def test_probe_and_finding_carry_timing_and_usage(tmp_path):
    store = FindingStore(tmp_path)
    timing = {"generate_ms": 10.0, "oracle_ms": 500.0, "round_ms": 600.0}
    usage = {"calls": 2, "total_tokens": 300, "cost_usd": 0.001}
    store.record_probe(
        spec=spec(),
        report={"verdict": "PASS"},
        seed_id="s1",
        category="pass",
        timing=timing,
        usage=usage,
    )
    probe = store.probes()[0]
    assert probe["timing"]["oracle_ms"] == 500.0
    assert probe["usage"]["total_tokens"] == 300

    fid = store.add_finding(
        spec=spec(),
        report=div_report(),
        triage=TRIAGE,
        seed_id="s1",
        timing=timing,
        usage=usage,
    )
    assert fid is not None
    finding = store.get_finding(fid)
    assert finding is not None
    assert finding["timing"]["round_ms"] == 600.0
    assert finding["usage"]["cost_usd"] == 0.001


def test_usage_summary_empty(tmp_path):
    store = FindingStore(tmp_path)
    assert store.usage_summary()["totals"]["calls"] == 0
