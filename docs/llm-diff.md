# LLM-guided differential fuzzing of Solidity compilers

Orientation doc for the research line in this repo: what the method is, how
the pieces map onto standard fuzzing vocabulary, and the process we follow
when developing and validating it. User-facing docs in `agent/README.md` and
`oracle/README.md`.

## Core logic

The method is a **feedback-driven fuzzing loop with an LLM as generator and
mutator**, running against a cross-chain differential oracle (solc/EVM on
anvil vs solang/Polkadot WASM on substrate-contracts-node). solc is the
declared reference: solang aims for source compatibility with solc 0.8 and
documents intentional deviations, so any undocumented behavioral divergence
is presumptively a solang bug.

Mapping onto standard fuzzing components:

| Fuzzing concept | Our realization | Where |
|---|---|---|
| Seed corpus | Feature seed cards (hand-written + distilled from historical bugs) | `agent/seeds/`, `agent/seeds_derived/` |
| Input corpus | Admitted specs with lineage and energy | `agent/src/agent/corpus.py` |
| Parent selection | Coverage-first over seed cards, then roulette on parent energy within a seed | `seeds.py`, `corpus.py` |
| Mutation | Programmatic sequence-level operators (free) + LLM batched source-level mutation (1 call → n mutants) | `mutate.py` |
| Oracle execution | Dual-chain compile-deploy-replay, batch-parallel | `executor.py`, `oracle/` |
| Feedback signal | Verdict + divergence kinds + per-seed hypothesis notebooks — the semantic replacement for coverage, which is incomparable across EVM and WASM backends | `triage.py`, `hypotheses.py`, `reflect.py` |
| Corpus admission | Divergence (novel fingerprint) / novel kind combination / seed bootstrap / unfiltered (control) | `corpus.py` |
| Power schedule | Energy: +1 divergent offspring, +2 novel, −0.1 invalid/duplicate; ×0.95 decay/round | `corpus.py` |
| Termination | Budget on oracle runs / LLM calls, plus saturation stop (K signal-free rounds) | `stop.py` |
| Crash triage | Deterministic known-difference rules first; LLM classification only for uncovered divergences | `triage.py`, `data/known_differences.json` |
| Unique-crash dedup | Fingerprint over divergence kinds + detail + source | `store.py` |
| Minimization | Delta-debugging on steps + LLM source shrinking, oracle-re-verified | `minimize.py` |

Two measured facts drive the design (dev hunt `findings/20260918`, 20
rounds):

1. **The LLM is the bottleneck, not the oracle.** 40.7 min cumulative LLM
   latency vs 0.5 min oracle time (~2.3 s/run). Hence batched mutation (one
   call, n mutants), free programmatic mutants, discard-no-repair for invalid
   mutants, and oracle runs (not LLM calls) as the fair budget axis in
   evaluation.
2. **Oracle noise burns the scarcest resource.** 30% of probes were triaged
   `oracle_artifact`, each costing triage + reflect calls. Hence artifact
   suppression inside the oracle's `compare.py` (raw values stay recorded)
   and promotion of recurring patterns to deterministic triage rules —
   every hardened rule is an LLM call saved forever.

What is deliberately *not* pursued: oracle throughput work (node reuse, warm
pools) — the measured profile does not justify it.

## Research / development process

Work proceeds in phases with explicit validation gates. Do not advance a
phase while its gate is failing.

### Phase 0 — invariants (always on)

- `uvx ruff check oracle/src oracle/tests agent/src agent/tests` and
  `uvx ruff format ...` after every change.
- `uv run --package solidity-diff-agent pytest agent/tests/ -m "not slow"`
  (unit; LLM and oracle are fakes) and
  `uv run --package solidity-diff-oracle pytest oracle/tests/` (e2e, `slow`).
- The oracle catches *all* unexpected node/compiler behavior as data —
  never crash the loop on it, never silently drop it.

### Phase 1 — oracle signal quality (gate: artifact regression)

Validate that suppressions kill the observed artifacts without losing true
positives:

- Replay the six findings from `findings/20260918` (`solidity-diff-agent
  replay <id>`): all must still report DIVERGENCE with the same kinds.
- Probe-level artifact regression needs a fresh dev hunt — probe specs are
  not persisted in `probes.jsonl` (only admitted corpus entries and findings
  carry full specs). Compare artifact rate and LLM calls/round against the
  20260918 baseline (~30% artifact rate, ~4 calls/round).

### Phase 2 — loop smoke test (gate: mutation round works end-to-end)

One small-budget hunt against real chains and the real LLM. Unit tests cover
the machinery with fakes; this is the only integration check. Watch for:
corpus admissions (`admitted_by`), mutant discard rate, energy evolution in
`corpus.jsonl`, stop reason sanity.

### Phase 3 — seed corpus (gate: human curation)

Offline pipeline (`agent/tools/fetch_bug_corpus.py` →
`distill_seeds.py` → human gate → `agent/seeds_derived/`). The raw cache
under `agent/data/bug_corpus/raw/` is committed and reviewable; distillation
operates on the cache only. Hunts consume the frozen corpus via
`--seeds-dir`.

### Phase 4 — evaluation (gate: pilot matrix, then full matrix)

- Pilot first: 2–3 configs × 2 repeats at a small budget, to shake out
  `evaluate.py` against the real LLM and to observe LLM-call variance across
  configs (mutation rounds have variable LLM cost).
- Full matrix: ablation axes are `p_mutate` (mutation on/off),
  `reflect` (feedback on/off), `admission` (interestingness vs
  random-restart), seed source (hand-written vs bug-derived). Common budget
  in oracle runs; ≥5 repeats per config (deterministic per-run rng seeds);
  report median/min/max, not distributional claims.
- Metrics (extracted per run, aggregated per config):
  `findings_per_100_oracle_runs`, `llm_calls_per_finding`,
  `mutant_discard_rate`, `corpus_admission_rate`, saturation series
  (cumulative unique findings vs oracle runs).

### Phase 5 — bug reporting (gate: verified, minimized, not-yet-known)

For each candidate: rule out documented differences (solang language docs)
and oracle/environment artifacts; check the solang issue tracker; replay the
minimized reproducer. Report upstream in the established style (MRE +
expected-vs-actual + solc comparison) and track confirmed/fixed status as a
first-class evaluation metric.

## Pointers

- `agent/README.md` — architecture, knobs, CLI.
- `oracle/README.md` — spec/report schema, comparison semantics.
