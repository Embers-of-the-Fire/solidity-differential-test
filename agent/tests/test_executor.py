from agent import executor as executor_module
from agent.executor import Executor


def test_execution_mode_is_materialized_on_retained_spec(monkeypatch):
    seen = []

    def fake_run(spec, verbose=False):
        seen.append(spec)
        return {"verdict": "PASS", "divergences": []}

    monkeypatch.setattr(executor_module, "run_spec_dict", fake_run)
    runner = Executor(parallel=1, execution_mode="dry-run-only")
    try:
        spec = {"name": "x", "steps": []}
        runner.run(spec)
        assert spec["execution"] == "dry-run-only"
        assert seen[0]["execution"] == "dry-run-only"
        batch = [{"name": "a"}, {"name": "b"}]
        runner.run_many(batch)
        assert all(s["execution"] == "dry-run-only" for s in batch)
    finally:
        runner.close()
