"""Unit tests for the verified reduction pipeline (L1) with a fake oracle.

No chain nodes: `run` is a pure function of the spec dict. solc is used for
gate-1 parse checks and AST spans (devshell binary, ~ms per call).
"""

from agent.minimize import Reducer, make_predicate, minimize

SIG = "RETURN_MISMATCH|0|f|int≠int"

SOURCE = """pragma solidity >=0.8.0;
contract C {
    uint256 x;
    function f(uint256 a) external { x = a; }
    function helper() external { x = 999; }
}
"""


def make_spec(n_steps=1, args=(5,)):
    return {
        "name": "m",
        "solidity": SOURCE,
        "contract": "C",
        "steps": [
            {"action": "call", "function": "f", "args": list(args)},
            *[{"action": "query", "function": f"junk{i}"} for i in range(n_steps - 1)],
        ],
    }


def signed_report(sig=SIG, point: object = 0):
    return {
        "verdict": "DIVERGENCE",
        "divergences": [
            {"kind": "RETURN_MISMATCH", "step": 0, "detail": "d", "signature": sig}
        ],
        "earliest_divergence": {"point": point, "signature": sig},
        "steps": [
            {"index": 0, "function": "f", "divergences": [{"kind": "RETURN_MISMATCH"}]}
        ],
    }


PASS = {"verdict": "PASS", "divergences": [], "earliest_divergence": None}


def fake_run(spec):
    """Diverges iff the witness core survives: f declared, its body intact,
    and a step still calls f. Argument values are irrelevant (the signature
    is value-free)."""
    src = spec.get("solidity", "")
    calls_f = any(s.get("function") == "f" for s in spec.get("steps", []))
    if "function f" in src and "x = a" in src and calls_f:
        return signed_report()
    return dict(PASS)


# --- predicate (T0.2) ---------------------------------------------------------


def test_signature_predicate_accepts_same_earliest_signature():
    accept = make_predicate(signed_report(), "signature")
    assert accept(signed_report())
    # downstream divergences may differ; the causal head decides
    extra = signed_report()
    extra["divergences"].append(
        {
            "kind": "STORAGE_MISMATCH",
            "step": 0,
            "detail": "s",
            "signature": "S2|0|f|multiset(count)",
        }
    )
    assert accept(extra)


def test_signature_predicate_rejects_drift_and_pass():
    accept = make_predicate(signed_report(), "signature")
    assert not accept(signed_report(sig="RETURN_MISMATCH|0|f|int≠null"))
    assert not accept(PASS)


def test_kind_predicate_is_lenient_superset():
    report = {
        "verdict": "DIVERGENCE",
        "divergences": [{"kind": "RETURN_MISMATCH", "step": 0, "detail": "d"}],
    }
    accept = make_predicate(report, "kind")
    assert accept(
        {
            "verdict": "DIVERGENCE",
            "divergences": [
                {"kind": "RETURN_MISMATCH"},
                {"kind": "STORAGE_MISMATCH"},
            ],
        }
    )
    assert not accept(
        {"verdict": "DIVERGENCE", "divergences": [{"kind": "EVENT_MISMATCH"}]}
    )


# --- pipeline stages ------------------------------------------------------------


def test_ddmin_steps_drops_unneeded_steps():
    spec = make_spec(n_steps=4)
    reducer = Reducer(signed_report(), fake_run)
    out = reducer.reduce_steps(spec)
    assert [s["function"] for s in out["steps"]] == ["f"]
    assert reducer.stats["ddmin_steps"] > 0


def test_steps_skipped_for_compile_point():
    report = signed_report(
        sig="COMPILE_ASYMMETRY|compile||solc-rejects", point="compile"
    )
    reducer = Reducer(report, fake_run)
    spec = make_spec(n_steps=3)
    assert reducer.reduce_steps(spec)["steps"] == spec["steps"]
    assert reducer.stats["ddmin_steps"] == 0


def test_dead_function_sweep_removes_uncalled_function():
    reducer = Reducer(signed_report(), fake_run)
    out = reducer.dead_function_sweep(make_spec())
    assert "helper" not in out["solidity"]
    assert "function f" in out["solidity"]


def test_ast_delete_removes_dead_state_variable():
    def run(spec):
        # x's declaration is load-bearing only via the fake: keep "x = a"
        return fake_run(spec)

    reducer = Reducer(signed_report(), run)
    out = reducer.ast_delete(make_spec())
    # helper() and its body are gone; f and its body survive
    assert "helper" not in out["solidity"]
    assert "x = a" in out["solidity"]


def test_arg_shrink_reduces_to_canonical_small_value():
    reducer = Reducer(signed_report(), fake_run)
    out = reducer.arg_shrink(make_spec(args=(255,)))
    assert out["steps"][0]["args"] == [0]


def test_full_pipeline_records_minimality():
    spec, meta = minimize(make_spec(n_steps=3), signed_report(), fake_run)
    assert [s["function"] for s in spec["steps"]] == ["f"]
    assert "helper" not in spec["solidity"]
    assert meta["verified_one_minimal"] is True
    assert meta["residual_deletable"] == 0
    assert meta["oracle_runs"] == sum(meta["stages"].values())


def test_cache_prevents_repeat_oracle_runs():
    calls = []

    def counting_run(spec):
        calls.append(1)
        return fake_run(spec)

    reducer = Reducer(signed_report(), counting_run)
    spec = make_spec()
    assert reducer._accepts(spec, _unlimited())
    assert reducer._accepts(spec, _unlimited())  # cache hit: no second run
    assert len(calls) == 1


def _unlimited():
    from agent.minimize import _Budget

    return _Budget(1 << 30, {"x": 0}, "x")
