from agent.hypotheses import (
    MAX_OPEN_HYPOTHESES,
    apply_ops,
    empty_notebook,
    load_notebook,
    render_for_prompt,
    save_notebook,
    summary_counts,
)

ADD = {"op": "add", "statement": "uint8 wraps on EVM", "next_probe": "try uint64"}


def test_add_and_persist(tmp_path):
    nb = empty_notebook("s1")
    nb, rejected = apply_ops(nb, [ADD])
    assert rejected == []
    assert nb["hypotheses"][0]["id"] == "h1"
    assert nb["hypotheses"][0]["status"] == "open"
    save_notebook(tmp_path, nb)
    loaded = load_notebook(tmp_path, "s1")
    assert loaded["hypotheses"][0]["statement"] == "uint8 wraps on EVM"


def test_load_missing_bootstraps_empty(tmp_path):
    nb = load_notebook(tmp_path, "nope")
    assert nb == {"seed_id": "nope", "hypotheses": [], "updated_ts": None}


def test_confirm_and_refute_transitions():
    nb = empty_notebook("s")
    nb, _ = apply_ops(nb, [ADD, {"op": "add", "statement": "x", "next_probe": "y"}])
    nb, rejected = apply_ops(
        nb,
        [
            {
                "op": "confirm",
                "id": "h1",
                "evidence": {"probe": "p", "verdict": "DIVERGENCE", "note": "n"},
            },
            {"op": "refute", "id": "h2"},
        ],
    )
    assert rejected == []
    statuses = {h["id"]: h["status"] for h in nb["hypotheses"]}
    assert statuses == {"h1": "confirmed", "h2": "refuted"}
    assert nb["hypotheses"][0]["evidence"][0]["probe"] == "p"


def test_terminal_states_are_immutable():
    nb = empty_notebook("s")
    nb, _ = apply_ops(nb, [ADD])
    nb, _ = apply_ops(nb, [{"op": "refute", "id": "h1"}])
    _, rejected = apply_ops(
        nb,
        [{"op": "confirm", "id": "h1"}, {"op": "refine", "id": "h1", "statement": "z"}],
    )
    assert len(rejected) == 2
    assert all("terminal" in r for r in rejected)
    # retarget is allowed on terminal hypotheses
    _, rejected = apply_ops(nb, [{"op": "retarget", "id": "h1", "next_probe": "q"}])
    assert rejected == []


def test_missing_id_rejected():
    nb = empty_notebook("s")
    _, rejected = apply_ops(nb, [{"op": "confirm", "id": "h9"}])
    assert len(rejected) == 1 and "does not exist" in rejected[0]


def test_invalid_ops_rejected_individually():
    nb = empty_notebook("s")
    nb, rejected = apply_ops(
        nb,
        [
            {"op": "frobnicate"},
            {"op": "add", "statement": "", "next_probe": "y"},
            {"op": "add", "statement": "ok", "next_probe": "z"},
            "not-an-object",
        ],
    )
    assert len(rejected) == 3
    assert [h["statement"] for h in nb["hypotheses"]] == ["ok"]


def test_open_cap_enforced():
    nb = empty_notebook("s")
    ops = [
        {"op": "add", "statement": f"s{i}", "next_probe": "p"}
        for i in range(MAX_OPEN_HYPOTHESES + 1)
    ]
    nb, rejected = apply_ops(nb, ops)
    assert len(nb["hypotheses"]) == MAX_OPEN_HYPOTHESES
    assert len(rejected) == 1 and "cap" in rejected[0]


def test_ids_never_reused():
    nb = empty_notebook("s")
    nb, _ = apply_ops(nb, [ADD, {"op": "add", "statement": "x", "next_probe": "y"}])
    assert [h["id"] for h in nb["hypotheses"]] == ["h1", "h2"]


def test_render_for_prompt():
    nb = empty_notebook("s")
    assert "no hypotheses yet" in render_for_prompt(nb)
    nb, _ = apply_ops(
        nb,
        [
            ADD,
            {"op": "add", "statement": "confirmed one", "next_probe": "p"},
            {"op": "add", "statement": "refuted one", "next_probe": "p"},
        ],
    )
    nb, _ = apply_ops(nb, [{"op": "confirm", "id": "h2"}, {"op": "refute", "id": "h3"}])
    text = render_for_prompt(nb)
    assert "[open] h1" in text and "NEXT PROBE: try uint64" in text
    assert "[confirmed] h2" in text
    assert "[refuted] h3" in text and "do NOT re-test" in text


def test_summary_counts():
    nb = empty_notebook("s")
    nb, _ = apply_ops(nb, [ADD, {"op": "add", "statement": "x", "next_probe": "y"}])
    nb, _ = apply_ops(nb, [{"op": "confirm", "id": "h2"}])
    assert summary_counts([nb]) == {"open": 1, "confirmed": 1, "refuted": 0}
