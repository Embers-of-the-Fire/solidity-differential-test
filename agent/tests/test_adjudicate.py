import json

from agent.adjudicate import (
    ReviewCase,
    adjudicate_cases,
    load_cases,
    screen_case,
)
from agent.config import AgentConfig
from agent.store import FindingStore
from agent.usage import NoUsage

SPEC = {
    "name": "review-case",
    "solidity": "contract C { function f() public pure returns (uint) { return 1; } }",
    "contract": "C",
    "steps": [{"action": "query", "function": "f"}],
}
REPORT = {
    "verdict": "DIVERGENCE",
    "divergences": [
        {
            "kind": "RETURN_MISMATCH",
            "step": 0,
            "detail": "return differs",
            "signature": "RETURN_MISMATCH|0|f|int≠int",
        }
    ],
    "earliest_divergence": {
        "point": 0,
        "signature": "RETURN_MISMATCH|0|f|int≠int",
    },
}
TRIAGE = {
    "category": "bug_candidate",
    "confidence": "low",
    "rationale": "unknown",
    "blame": "neither",
    "summary": "return differs",
}


class PanelLLM(NoUsage):
    def __init__(self, votes=2, reject=False):
        self.calls = 0
        self.votes = votes
        self.reject = reject
        self.prompts = []
        self.panel_calls = 0

    def budget_left(self):
        return 100

    def chat_json(self, system, user, *, validate=None, **kwargs):
        self.calls += 1
        self.prompts.append(user)
        if "adversarial" in system:
            result = {
                "rebuttal_succeeds": self.reject,
                "category": "oracle_artifact" if self.reject else "bug_candidate",
                "evidence": "concrete evidence",
                "rationale": "adversarial rationale",
                "historical_match_url": "",
            }
        else:
            self.panel_calls += 1
            result = {
                "category": "bug_candidate"
                if self.panel_calls % 2 == 1
                else ("bug_candidate" if self.votes == 2 else "oracle_artifact"),
                "confidence": "medium",
                "evidence": "return values 1 and 2",
                "rationale": "panel rationale",
                "historical_match_url": "",
                "cluster_hint": "incorrect return lowering",
            }
        if validate:
            assert validate(result) == []
        return result


def case():
    return ReviewCase("finding-f1", SPEC, REPORT, probe_id="p1", finding_id="f1")


def test_panel_and_adversarial_survivor():
    llm = PanelLLM(votes=2, reject=False)
    result = screen_case(llm, case(), judges=2, known_differences=[], history=[])
    assert result["survives"] is True
    assert result["panel_bug_votes"] == 2
    assert result["cluster_hint"] == "incorrect return lowering"
    assert llm.calls == 3


def test_majority_is_required_and_failed_panel_skips_adversary():
    llm = PanelLLM(votes=1)
    result = screen_case(llm, case(), judges=2, known_differences=[], history=[])
    assert result["survives"] is False
    assert result["adversarial"] is None
    assert llm.calls == 2


def test_adversary_can_reject_unanimous_panel():
    result = screen_case(
        PanelLLM(votes=2, reject=True),
        case(),
        judges=2,
        known_differences=[],
        history=[],
    )
    assert result["survives"] is False
    assert result["status"] == "rejected"


def test_rejected_sampling_is_reproducible_and_resumes(tmp_path):
    store = FindingStore(tmp_path)
    for i in range(5):
        store.record_probe(
            spec={**SPEC, "name": f"rejected-{i}"},
            report=REPORT,
            seed_id="s",
            category="oracle_artifact",
        )
    first = load_cases(tmp_path, include_findings=False, rejected_sample=2, rng_seed=9)
    second = load_cases(tmp_path, include_findings=False, rejected_sample=2, rng_seed=9)
    assert [c.case_id for c in first] == [c.case_id for c in second]
    assert all(c.origin == "rejected_probe" for c in first)

    cfg = AgentConfig(findings_dir=tmp_path / "review")
    counts = adjudicate_cases(
        PanelLLM(), cfg, tmp_path, first, judges=2, repo_root=tmp_path
    )
    assert counts["survivor"] == 2
    counts = adjudicate_cases(
        PanelLLM(), cfg, tmp_path, first, judges=2, repo_root=tmp_path
    )
    assert counts["skipped"] == 2
    records = [
        json.loads(line)
        for line in (tmp_path / "review" / "screening.jsonl").read_text().splitlines()
    ]
    assert len(records) == 2
    assert all("usage" in r for r in records)
    for selected in first:
        assert (
            tmp_path / "review" / "dossiers" / selected.case_id / "dossier.md"
        ).exists()


def test_findings_and_rejected_probes_are_both_available(tmp_path):
    store = FindingStore(tmp_path)
    probe_id = store.record_probe(
        spec=SPEC,
        report=REPORT,
        seed_id="s",
        category="oracle_artifact",
    )
    finding_id = store.add_finding(
        spec=SPEC,
        report=REPORT,
        triage=TRIAGE,
        seed_id="s",
        origin_probe_id=probe_id,
    )
    assert finding_id is not None
    cases = load_cases(tmp_path, rejected_sample=1)
    assert {c.origin for c in cases} == {"finding", "rejected_probe"}
    finding = next(c for c in cases if c.origin == "finding")
    assert finding.probe_id == probe_id
