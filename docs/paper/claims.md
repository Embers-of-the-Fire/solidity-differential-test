# Claims — DRAFT scaffold

Three checkable claims, each wired to the experiment that supports it.

## C1 — Precision

Witnesses reported by the loop are genuine compiler/chain behavioral
divergences, not oracle artifacts.

- Evidence: rediscovery of known historical solang bugs
  (`agent/data/ground_truth/`, validated by `eval/rq1/oracle_validation.json`;
  hunter rediscovery rate from `eval/rq1/rediscovery.json` — T3.1, requires
  LLM budget); manual audit of signatures
  (`docs/agents/refine/notes/signature-audit.md`); exact-vs-count storage
  false-positive measurement (`eval/rq1/storage_modes.json`: 2 of 5
  exact-mode STORAGE_MISMATCH divergences are layout artifacts that vanish
  under count mode — motivates the default).

## C2 — Effectiveness

The loop finds previously unknown divergences on the latest solang.

- Evidence: grown witness corpus under `findings/hunt-latest/` (T3.2,
  requires LLM budget); the seed corpus `findings/20260923/` (3 witnesses,
  exported in `dataset/witnesses/`) as the existence proof of the pipeline.

## C3 — Verified reduction is cheap and tight

The staged pipeline (ddmin steps → dead-function sweep → AST deletion →
arg shrink → LLM simplify) produces verified 1-minimal witnesses at a cost
of tens of oracle runs (~60 ms marginal cost per step; node boot dominates
at ~1.1 s and is paid once per run).

- Evidence: `eval/rq3/reduction.json` (per-witness chars/steps before→after,
  per-stage oracle runs, `verified_one_minimal`); 1-minimality verification
  is exhaustive over single deletions/one-notch shrinks
  (`agent/src/agent/minimize.py`, `verify_one_minimal`).
