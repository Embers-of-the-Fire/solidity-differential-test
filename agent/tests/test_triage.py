from agent import triage
from agent.triage import classify_by_rules, triage_report
from agent.usage import NoUsage


class FakeLLM(NoUsage):
    """Stands in for LLMClient; records prompts, returns canned JSON."""

    def __init__(self, reply):
        self.reply = reply
        self.calls = 0

    def budget_left(self):
        return 100 - self.calls

    def chat_json(
        self, system, user, *, validate=None, max_attempts=3, stage="unknown"
    ):
        self.calls += 1
        if validate:
            problems = validate(self.reply)
            assert not problems, problems
        return self.reply


def div(kind, detail="d"):
    return {"kind": kind, "step": 0, "detail": detail, "evm": 1, "polkadot": 2}


def test_rule_catches_gasleft_return_mismatch():
    d = div("RETURN_MISMATCH")
    source = (
        "contract c { function f() public view returns (uint) { return gasleft(); } }"
    )
    assert classify_by_rules(d, source) == "known_semantic"


def test_rule_catches_block_number():
    d = div("RETURN_MISMATCH")
    source = "contract c { function f() public view returns (uint) { return block.number; } }"
    assert classify_by_rules(d, source) == "known_semantic"


def test_rule_ignores_plain_return_mismatch():
    d = div("RETURN_MISMATCH")
    source = "contract c { function f() public pure returns (uint) { return 1 + 1; } }"
    assert classify_by_rules(d, source) is None


def test_triage_pass_needs_no_llm():
    llm = FakeLLM({})
    out = triage_report(
        llm, {"solidity": "..."}, {"verdict": "PASS", "divergences": []}
    )
    assert out["category"] == "pass"
    assert llm.calls == 0


def test_triage_known_semantic_all_rules_needs_no_llm():
    llm = FakeLLM({})
    report = {"verdict": "DIVERGENCE", "divergences": [div("RETURN_MISMATCH")]}
    spec = {"solidity": "return block.timestamp;"}
    out = triage_report(llm, spec, report)
    assert out["category"] == "known_semantic"
    assert out["rule_based"]
    assert llm.calls == 0


def test_triage_error_verdict():
    out = triage_report(FakeLLM({}), {}, {"verdict": "ERROR", "error": "boom"})
    assert out["category"] == "error"


def test_triage_llm_classification():
    reply = {
        "category": "bug_candidate",
        "confidence": "high",
        "rationale": "1+1 returned 3 on polkadot",
        "blame": "solang",
        "summary": "addition broken on solang",
    }
    llm = FakeLLM(reply)
    report = {"verdict": "DIVERGENCE", "divergences": [div("RETURN_MISMATCH")]}
    out = triage_report(llm, {"solidity": "return 1 + 1;"}, report)
    assert out["category"] == "bug_candidate"
    assert llm.calls == 1


ARTIFACT_RULES = [
    {
        "id": "dry-run-dispatch-error",
        "kinds": ["STATUS_MISMATCH"],
        "category": "oracle_artifact",
        "source_markers": [],
        "rationale": "pallet dry-run module error, committed tx agrees",
    },
    {
        "id": "legacy-no-category",
        "kinds": ["GAS_MISMATCH"],
        "source_markers": [],
        "rationale": "old schema without category field",
    },
]


def test_rule_category_oracle_artifact(monkeypatch):
    monkeypatch.setattr(triage, "_known_rules", lambda: ARTIFACT_RULES)
    assert classify_by_rules(div("STATUS_MISMATCH"), "contract c {}") == (
        "oracle_artifact"
    )


def test_rule_without_category_defaults_known_semantic(monkeypatch):
    monkeypatch.setattr(triage, "_known_rules", lambda: ARTIFACT_RULES)
    assert classify_by_rules(div("GAS_MISMATCH"), "contract c {}") == "known_semantic"


def test_triage_artifact_rules_need_no_llm(monkeypatch):
    monkeypatch.setattr(triage, "_known_rules", lambda: ARTIFACT_RULES)
    llm = FakeLLM({})
    report = {"verdict": "DIVERGENCE", "divergences": [div("STATUS_MISMATCH")]}
    out = triage_report(llm, {"solidity": "contract c {}"}, report)
    assert out["category"] == "oracle_artifact"
    assert out["rule_based"]
    assert llm.calls == 0


def test_triage_mixed_categories_prefer_known_semantic(monkeypatch):
    monkeypatch.setattr(triage, "_known_rules", lambda: ARTIFACT_RULES)
    llm = FakeLLM({})
    report = {
        "verdict": "DIVERGENCE",
        "divergences": [div("STATUS_MISMATCH"), div("GAS_MISMATCH")],
    }
    out = triage_report(llm, {"solidity": "contract c {}"}, report)
    assert out["category"] == "known_semantic"
    assert llm.calls == 0


def test_triage_artifact_plus_unmatched_falls_to_llm(monkeypatch):
    monkeypatch.setattr(triage, "_known_rules", lambda: ARTIFACT_RULES)
    reply = {
        "category": "bug_candidate",
        "confidence": "medium",
        "rationale": "unexplained return difference",
        "blame": "solang",
        "summary": "return differs",
    }
    llm = FakeLLM(reply)
    report = {
        "verdict": "DIVERGENCE",
        "divergences": [div("STATUS_MISMATCH"), div("RETURN_MISMATCH")],
    }
    out = triage_report(llm, {"solidity": "contract c {}"}, report)
    assert out["category"] == "bug_candidate"
    assert llm.calls == 1
