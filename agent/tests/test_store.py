from agent.store import FindingStore, fingerprint


def spec(source="contract c {}", name="x"):
    return {"name": name, "solidity": source, "contract": "c", "steps": []}


def div_report(kind="RETURN_MISMATCH", detail="dry-run return values differ"):
    return {
        "verdict": "DIVERGENCE",
        "divergences": [{"kind": kind, "step": 0, "detail": detail}],
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
    report = store.report_for(fid)
    assert report is not None and report["verdict"] == "DIVERGENCE"


def test_fingerprint_normalizes_whitespace_and_case():
    a = fingerprint(
        {"RETURN_MISMATCH"}, "Dry-Run  RETURN values differ", "contract c  { }"
    )
    b = fingerprint(
        {"RETURN_MISMATCH"}, "dry-run return values differ", "contract c { }"
    )
    assert a == b


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
