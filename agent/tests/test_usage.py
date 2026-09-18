"""Unit tests for usage/cost tracing (no server, no chain nodes)."""

import json

from agent.usage import (
    NoUsage,
    Pricing,
    UsageTracker,
    extract_usage,
    summarize,
    summarize_jsonl,
)


def make_usage(prompt=100, completion=50, cached=None):
    usage: dict = {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
    }
    if cached is not None:
        usage["prompt_tokens_details"] = {"cached_tokens": cached}
    return usage


def test_extract_usage_flat():
    fields = extract_usage(make_usage(100, 50, cached=40))
    assert fields["prompt_tokens"] == 100
    assert fields["cached_prompt_tokens"] == 40
    assert fields["completion_tokens"] == 50
    assert fields["total_tokens"] == 150
    assert fields["usage_raw"]["prompt_tokens"] == 100


def test_extract_usage_missing():
    fields = extract_usage(None)
    assert fields["prompt_tokens"] is None
    assert fields["cached_prompt_tokens"] is None
    assert fields["usage_raw"] is None


def test_pricing_uncached_only():
    p = Pricing(input_per_1m=2.0, output_per_1m=8.0)
    # 1M uncached in + 1M out
    assert p.cost_usd(1_000_000, 0, 1_000_000) == 10.0


def test_pricing_cached_split():
    p = Pricing(input_per_1m=2.0, cached_input_per_1m=0.5, output_per_1m=8.0)
    # 600k uncached + 400k cached + 1M out
    cost = p.cost_usd(1_000_000, 400_000, 1_000_000)
    assert abs(cost - (0.6 * 2.0 + 0.4 * 0.5 + 8.0)) < 1e-12


def test_pricing_cached_defaults_to_input_rate():
    p = Pricing(input_per_1m=2.0, output_per_1m=8.0)
    assert p.cost_usd(1_000_000, 400_000, 0) == 2.0


def test_tracker_records_stage_attempt_and_writes_jsonl(tmp_path):
    tracker = UsageTracker(tmp_path / "llm_usage.jsonl", pricing=Pricing())
    tracker.set_context("generate", 0)
    rec = tracker.record(
        model="m", temperature=1.0, latency_ms=12.5, usage_raw=make_usage()
    )
    assert rec["stage"] == "generate"
    assert rec["attempt"] == 0
    assert rec["cost_usd"] == 0.0  # free local pricing
    assert rec["error"] is None

    tracker.set_context("triage", 1)
    tracker.record(model="m", temperature=1.0, latency_ms=1.0, error="boom")

    lines = (tmp_path / "llm_usage.jsonl").read_text().strip().splitlines()
    assert len(lines) == 2
    persisted = json.loads(lines[1])
    assert persisted["stage"] == "triage"
    assert persisted["attempt"] == 1
    assert persisted["error"] == "boom"
    assert persisted["cost_usd"] is None  # no usage -> no cost


def test_tracker_marker_and_records_since(tmp_path):
    tracker = UsageTracker(None)
    tracker.record(model="m", temperature=0.0, latency_ms=1.0, usage_raw=make_usage())
    mark = tracker.marker()
    tracker.record(
        model="m", temperature=0.0, latency_ms=2.0, usage_raw=make_usage(10, 5)
    )
    delta = tracker.records_since(mark)
    assert len(delta) == 1
    assert delta[0]["total_tokens"] == 15


def test_summarize_totals_and_per_stage():
    records = [
        {
            "stage": "generate",
            "latency_ms": 10.0,
            **extract_usage(make_usage(100, 50)),
            "cost_usd": 0.1,
            "error": None,
        },
        {
            "stage": "generate",
            "latency_ms": 30.0,
            **extract_usage(make_usage(200, 100)),
            "cost_usd": 0.2,
            "error": None,
        },
        {"stage": "reflect", "latency_ms": 5.0, "error": "x"},
    ]
    out = summarize(records)
    totals = out["totals"]
    assert totals["calls"] == 3
    assert totals["errors"] == 1
    assert totals["prompt_tokens"] == 300
    assert totals["completion_tokens"] == 150
    assert totals["total_tokens"] == 450
    assert abs(totals["cost_usd"] - 0.3) < 1e-12
    assert totals["avg_latency_ms"] == 15.0
    gen = out["per_stage"]["generate"]
    assert gen["calls"] == 2
    assert gen["total_tokens"] == 450


def test_summarize_jsonl_missing_file(tmp_path):
    out = summarize_jsonl(tmp_path / "nope.jsonl")
    assert out["totals"]["calls"] == 0


def test_summarize_jsonl_roundtrip(tmp_path):
    tracker = UsageTracker(tmp_path / "llm_usage.jsonl")
    tracker.record(model="m", temperature=0.0, latency_ms=1.0, usage_raw=make_usage())
    out = summarize_jsonl(tmp_path / "llm_usage.jsonl")
    assert out["totals"]["calls"] == 1
    assert out["totals"]["total_tokens"] == 150


def test_no_usage_mixin_zeroes():
    class Fake(NoUsage):
        pass

    f = Fake()
    assert f.usage_marker() == 0
    assert f.usage_since(0)["totals"]["calls"] == 0
    assert f.usage_totals()["totals"]["cost_usd"] == 0.0


def test_llm_client_records_usage_with_cached_tokens(monkeypatch, tmp_path):
    """LLMClient wires the tracker: tokens, cache split, cost, JSONL, stage."""
    from types import SimpleNamespace

    from agent.config import AgentConfig
    from agent.llm import LLMClient

    cfg = AgentConfig(
        base_url="http://x.invalid/v1",
        model="m",
        findings_dir=tmp_path,
        price_input_per_1m=2.0,
        price_cached_input_per_1m=0.5,
        price_output_per_1m=8.0,
    )
    client = LLMClient(cfg)
    usage_payload = {
        "prompt_tokens": 1000,
        "completion_tokens": 500,
        "total_tokens": 1500,
        "prompt_tokens_details": {"cached_tokens": 400},
    }
    usage = SimpleNamespace(
        **{k: v for k, v in usage_payload.items() if k != "prompt_tokens_details"},
        prompt_tokens_details=SimpleNamespace(cached_tokens=400),
        model_dump=lambda: dict(usage_payload),
    )
    resp = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))],
        usage=usage,
    )
    monkeypatch.setattr(client._client.chat.completions, "create", lambda **kw: resp)

    out = client.chat_json("sys", "user", stage="triage")
    assert out == {}
    assert client.calls == 1
    rec = client.usage.records[0]
    assert rec["stage"] == "triage"
    assert rec["attempt"] == 0
    assert rec["prompt_tokens"] == 1000
    assert rec["cached_prompt_tokens"] == 400
    assert rec["completion_tokens"] == 500
    assert rec["latency_ms"] >= 0
    # 600 uncached*2 + 400 cached*0.5 + 500 out*8, per 1M
    assert abs(rec["cost_usd"] - (600 * 2.0 + 400 * 0.5 + 500 * 8.0) / 1e6) < 1e-12
    assert rec["usage_raw"]["prompt_tokens_details"]["cached_tokens"] == 400
    assert (tmp_path / "llm_usage.jsonl").exists()

    totals = client.usage_totals()["totals"]
    assert totals["calls"] == 1
    assert totals["cached_prompt_tokens"] == 400


def test_llm_client_records_api_errors(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from agent.config import AgentConfig
    from agent.llm import LLMClient, LLMError

    cfg = AgentConfig(base_url="http://x.invalid/v1", model="m", findings_dir=tmp_path)
    client = LLMClient(cfg)

    def boom(**kw):
        from openai import APIConnectionError

        raise APIConnectionError(request=SimpleNamespace())

    monkeypatch.setattr(client._client.chat.completions, "create", boom)
    try:
        client.chat("sys", "user", max_retries=2)
        raise AssertionError("should have raised")
    except LLMError:
        pass
    assert len(client.usage.records) == 2
    assert all(r["error"] for r in client.usage.records)
    assert all(r["cost_usd"] is None for r in client.usage.records)
