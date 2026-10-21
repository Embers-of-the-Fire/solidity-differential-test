# Evaluation — DRAFT scaffold

All campaigns write under `eval/<rq>/` and reuse the eval harness
(`agent/src/agent/evaluate.py`: config × repeat, deterministic `rng_seed`,
failed runs recorded, budgets in oracle runs). n = 5 repeats → median +
min/max only, no distributional claims.

## RQ1 — Precision

(a) Ground truth: 6 hand-encoded historical solang bugs
(`agent/data/ground_truth/`), each validated DIVERGENCE-on-affected /
PASS-on-fixed (`eval/rq1/oracle_validation.json`, current status: 6/6
admitted). (b) Hunter rediscovery: matrix `agent/eval/rq1_rediscovery.json`
({full, no-mutate, no-reflect, no-admit} × 5 repeats, 300 oracle runs/run,
pinned old solang via ORACLE_SOLANG_BIN) → `eval/rq1/rediscovery.json`
(T3.1 — requires LLM budget). (c) Storage-mode FP rate:
`eval/rq1/storage_modes.json`.

| ground-truth bug | affected | rediscovered by full? | no-mutate? | ... |
|---|---|---|---|---|
| (from eval/rq1/rediscovery.json — pending LLM budget) | | | | |

| storage mode | STORAGE_MISMATCH count | spurious under count |
|---|---|---|
| exact | 5 | 2 (from eval/rq1/storage_modes.json) |

## RQ2 — Effectiveness

Long hunt on the pinned latest solang (T3.2 — requires LLM budget) →
`findings/hunt-latest/`. Witness table: id, signature, chars/steps after
reduction, triage blame.

## RQ3 — Reduction

`eval/rq3/reduction.json`: per witness, chars/steps before→after, oracle
runs per stage, `verified_one_minimal`; predicate-drift arm (kind predicate)
with manual audit (`docs/agents/refine/notes/drift-audit.md`, N=3, 0 drift —
methodology datum only).

| witness | chars before→after | steps before→after | oracle runs | 1-minimal? | drift (kind arm) |
|---|---|---|---|---|---|
| revert-reason-payloads | 176→56 | 1→1 | 1 | yes | no |
| event-indexed-emission-matrix | 581→486 | 1→1 | 11 | yes | no |
| crypto-packed-encoding-hashes | 484→410 (sig) / 484 (kind) | 2→1 (sig) / 2 (kind) | 11/10 | yes | no |

## RQ4 — Architecture justification

On-chain replay vs dry-run-only contrast (`eval/rq4/contrast.json`, current
corpus): witness classes invisible without committed replay
(`replay-required`), witnesses whose dry-run-only verdict drifts to a
*different* divergence (`divergence-drifted` — the pallet dry-run dispatch
error artifact becomes unsuppressible), and pure dry-run false positives
(`dry-run-artifact`).

| classification | count (current corpus, N=9) |
|---|---|
| replay-irrelevant | 3 |
| replay-required | 2 |
| divergence-drifted | 4 |

## RQ5 — Cost, ablations, determinism

Ablation matrix `agent/eval/rq5_ablations.json` (architecture ablations +
reduction ablations ddmin-only/llm-only/kind-predicate) — requires LLM
budget. Cost aggregation via the `cost` CLI (llm_usage.jsonl, tier-split by
`agent/src/agent/usage.py`). Determinism: `agent/tools/replay_check.py`
replays every final witness 5× → `eval/rq5/determinism.json` (current
corpus: 3/3 verdict- and signature-stable).
