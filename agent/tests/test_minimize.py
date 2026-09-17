from agent.minimize import minimize_steps


def make_spec(n_steps):
    return {
        "name": "m",
        "solidity": "contract c {}",
        "contract": "c",
        "steps": [{"action": "call", "function": f"f{i}"} for i in range(n_steps)],
    }


def report_with(kind):
    return {
        "verdict": "DIVERGENCE",
        "divergences": [{"kind": kind, "step": None, "detail": "d"}],
    }


PASS = {"verdict": "PASS", "divergences": []}


def test_step_pruning_removes_unneeded_steps():
    # divergence persists as long as f2 is present
    def run(spec):
        fns = {s["function"] for s in spec["steps"]}
        return report_with("RETURN_MISMATCH") if "f2" in fns else PASS

    out = minimize_steps(make_spec(4), {"RETURN_MISMATCH"}, run, max_oracle_runs=20)
    assert [s["function"] for s in out["steps"]] == ["f2"]


def test_step_pruning_respects_budget():
    calls = []

    def run(spec):
        calls.append(len(spec["steps"]))
        return report_with("RETURN_MISMATCH")

    out = minimize_steps(make_spec(5), {"RETURN_MISMATCH"}, run, max_oracle_runs=2)
    assert len(calls) == 2
    assert len(out["steps"]) == 3  # only two removals applied


def test_step_pruning_keeps_needed_steps():
    # any removal kills the divergence
    out = minimize_steps(make_spec(3), {"RETURN_MISMATCH"}, lambda s: PASS)
    assert len(out["steps"]) == 3
