"""Unit tests for ddmin (T1.1): crafted fake predicates, no oracle."""

from agent.ddmin import ddmin


def test_ddmin_single_relevant_item():
    items = ["a", "b", "c", "d"]
    out = ddmin(items, lambda cand: "c" in cand)
    assert out == ["c"]


def test_ddmin_recovers_pair_dependency_where_greedy_stalls():
    # greedy single-deletion stalls here: removing either of "a"/"b" alone
    # kills the property, so a one-at-a-time pruner keeps everything
    items = ["a", "b", "x", "y"]
    out = ddmin(items, lambda cand: "a" in cand and "b" in cand)
    assert sorted(out) == ["a", "b"]


def test_ddmin_empty_interesting_set():
    # textbook ddmin is defined on non-empty results: it converges to a single
    # element even when the empty list is interesting
    out = ddmin(["a", "b", "c"], lambda cand: True)
    assert len(out) == 1


def test_ddmin_never_returns_superset_of_accepted_intermediate():
    accepted: list[list[str]] = []

    def test(cand):
        ok = "b" in cand
        if ok:
            accepted.append(list(cand))
        return ok

    out = ddmin(["a", "b", "c", "d", "e"], test)
    assert out == ["b"]
    for intermediate in accepted:
        assert set(out) <= set(intermediate)


def test_ddmin_all_needed():
    items = [1, 2, 3]
    out = ddmin(items, lambda cand: len(cand) == 3)
    assert out == [1, 2, 3]
