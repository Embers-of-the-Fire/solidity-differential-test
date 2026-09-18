from agent.hypotheses import load_notebook
from agent.llm import LLMError
from agent.reflect import reflect_notebook
from agent.seeds import Seed
from agent.usage import NoUsage

SEED = Seed(id="int-semantics", title="Ints", why="casts", hints=[])
SPEC = {"name": "p1", "solidity": "contract c {}", "contract": "c", "steps": []}
REPORT = {
    "verdict": "DIVERGENCE",
    "divergences": [{"kind": "RETURN_MISMATCH", "detail": "d"}],
}
TRIAGE = {"category": "bug_candidate"}


class FakeLLM(NoUsage):
    calls: int

    def __init__(self, reply=None, error=None):
        self.reply = reply
        self.error = error
        self.calls = 0
        self.last_user: str = ""

    def budget_left(self) -> int:
        return 100 - self.calls

    def chat_json(
        self, system, user, *, validate=None, max_attempts=3, stage="unknown"
    ) -> dict:
        self.calls += 1
        self.last_user = user
        if self.error:
            raise self.error
        if validate:
            problems = validate(self.reply)
            assert not problems, problems
        assert self.reply is not None
        return self.reply


def test_reflect_adds_hypothesis(tmp_path):
    llm = FakeLLM(
        {
            "ops": [
                {
                    "op": "add",
                    "statement": "uint8 wraps on EVM",
                    "next_probe": "try uint64",
                    "evidence": {
                        "probe": "p1",
                        "verdict": "DIVERGENCE",
                        "note": "44 vs 300",
                    },
                }
            ],
            "reasoning": "overflow behaved differently",
        }
    )
    nb = reflect_notebook(
        llm, tmp_path, SEED, SPEC, REPORT, TRIAGE, log=lambda *_: None
    )
    assert nb["hypotheses"][0]["statement"] == "uint8 wraps on EVM"
    # persisted to disk
    assert load_notebook(tmp_path, "int-semantics")["hypotheses"][0]["id"] == "h1"


def test_reflect_rejects_bad_ops_but_applies_good(tmp_path):
    llm = FakeLLM(
        {
            "ops": [
                {"op": "confirm", "id": "h99"},  # missing id -> rejected
                {"op": "add", "statement": "s", "next_probe": "p"},
            ],
            "reasoning": "r",
        }
    )
    logs = []
    nb = reflect_notebook(llm, tmp_path, SEED, SPEC, REPORT, TRIAGE, log=logs.append)
    assert [h["statement"] for h in nb["hypotheses"]] == ["s"]
    assert any("rejected" in line for line in logs)


def test_reflect_llm_failure_keeps_notebook(tmp_path):
    llm = FakeLLM(error=LLMError("boom"))
    logs = []
    nb = reflect_notebook(llm, tmp_path, SEED, SPEC, REPORT, TRIAGE, log=logs.append)
    assert nb["hypotheses"] == []
    assert any("skipped" in line for line in logs)


def test_reflect_empty_ops_not_saved(tmp_path):
    llm = FakeLLM({"ops": [], "reasoning": "nothing new"})
    nb = reflect_notebook(
        llm, tmp_path, SEED, SPEC, REPORT, TRIAGE, log=lambda *_: None
    )
    assert nb["hypotheses"] == []
    assert not (tmp_path / "hypotheses" / "int-semantics.json").exists()


def test_reflect_prompt_carries_notebook_and_probe(tmp_path):
    # seed the notebook, then check the next reflect prompt includes it
    llm = FakeLLM(
        {
            "ops": [{"op": "add", "statement": "h-one", "next_probe": "np"}],
            "reasoning": "r",
        }
    )
    reflect_notebook(llm, tmp_path, SEED, SPEC, REPORT, TRIAGE, log=lambda *_: None)
    reflect_notebook(llm, tmp_path, SEED, SPEC, REPORT, TRIAGE, log=lambda *_: None)
    assert '"statement": "h-one"' in llm.last_user
    assert "p1" in llm.last_user
