"""Unit tests for argument shrinking (T1.4): candidate orderings and the
strict rank decrease that prevents lateral ping-pong."""

from agent.shrink_args import rank, shrink_candidates, value_candidates, with_arg


def test_ints_shrink_toward_zero_one():
    assert value_candidates(255)[:2] == [0, 1]
    assert value_candidates(-7) == [0, 1, -1]
    assert value_candidates(0) == [1]  # 0 itself excluded
    assert value_candidates(1) == [0]


def test_strings_shrink_toward_empty():
    assert value_candidates("hello") == ["", "a"]
    assert value_candidates("") == ["a"]
    assert value_candidates("a") == [""]


def test_bytes_shrink_toward_empty_then_halved():
    assert value_candidates("0x01020304") == ["0x", "0x0102"]
    assert value_candidates("0x01") == ["0x"]
    assert value_candidates("0x") == []


def test_addresses_shrink_to_canonical_label():
    assert value_candidates("0x" + "ab" * 20) == ["$alice"]
    assert value_candidates("$alice") == []  # already canonical


def test_arrays_truncate_then_shrink_elements():
    cands = value_candidates([5, 6])
    assert cands[0] == []
    assert [5] in cands
    assert [0, 6] in cands  # element-wise one-notch
    assert value_candidates([]) == []


def test_bools_shrink_to_false():
    assert value_candidates(True) == [False]
    assert value_candidates(False) == []


def test_candidates_strictly_decrease_rank():
    values = [255, -7, "hello", "0x01020304", "0x" + "ab" * 20, [5, 6], True]
    for v in values:
        for cand in value_candidates(v):
            assert rank(cand) <= rank(v), f"{cand!r} not simpler than {v!r}"


def test_shrink_candidates_filters_lateral_moves():
    spec = {
        "steps": [
            {"function": "f", "args": [0, 255]},
        ]
    }
    triples = list(shrink_candidates(spec))
    # arg 0 is already rank 0 -> no candidates; arg 1 -> 0 and 1
    assert [(i, j) for i, j, _ in triples] == [(0, 1), (0, 1)]


def test_with_arg_replaces_deeply():
    spec = {"steps": [{"function": "f", "args": [5, "x"]}]}
    out = with_arg(spec, 0, 1, "")
    assert out["steps"][0]["args"] == [5, ""]
    assert spec["steps"][0]["args"] == [5, "x"]  # original untouched
