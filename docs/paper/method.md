# Method — DRAFT scaffold

## Spec model and state threading

A test environment is a JSON spec: Solidity source, target contract,
constructor args, and a sequence of steps (`call` = state-changing
transaction, `query` = read-only dry run). The same spec drives both chains:
solc bytecode on anvil (EVM), solang WASM on substrate-contracts-node
(pallet-contracts). Steps execute in order; committed transactions thread
state forward on both chains. (Schema: `oracle/src/oracle/spec.py`.)

## The oracle as a projection π

Cross-chain state is intentionally incommensurable (EVM slots vs Polkadot
child-trie cells, different endianness and packing). The oracle therefore
compares only the projection π of each execution:

- dry-run status / return value / revert reason per step;
- committed-tx status, event log (name + args), post-tx storage summary;
- storage comparison is a zero-stripped, signed-canonicalized value
  multiset in the default `count` mode (slot packing makes counts
  layout-dependent; `exact` mode exists for FP measurement — see RQ1).

**Never compared** (recorded for traceability only): block number/hash/
timestamp, account balances, gas (EVM gas vs Substrate weights are
incommensurable; gas comparison is opt-in), wall-clock timing.

Known-artifact suppressions (pallet dry-run dispatch error corroborated by a
matching committed tx; error-vs-revert committed statuses; byte-equal return
serializations) are enumerated in `oracle/src/oracle/compare.py`.

## Witnesses and signatures

A witness is identified by the signature of its **earliest** divergence —
strict at the causal head, tolerant of downstream consequences:

```
point     = "compile" | "deploy" | <step index>
signature = "<kind>|<point>|<function-or-empty>|<relation>"
```

`relation` is a per-kind structural descriptor of the normalized payloads
(status pair, type-shape pair, reason-class pair, first structural event
difference, storage mode tag) — deliberately value-free, because argument
shrinking changes values without changing the bug. (Implementation:
`oracle/src/oracle/signature.py`; audit: `docs/agents/refine/notes/signature-audit.md`.)

## Verified reduction

Pipeline (fixed order, one shared acceptance predicate = earliest-signature
equality, budgets in oracle runs):

1. **ddmin steps** — generic delta debugging over the step list
   (skipped for compile/deploy-point witnesses).
2. **Dead-function sweep** — one batched deletion of functions no surviving
   step references.
3. **AST-guided deletion** — solc `--ast-compact-json` byte spans, queue order
   FunctionDefinition → state VariableDeclaration → EventDefinition →
   ErrorDefinition → ModifierDefinition → statements; two-gate verification
   (`solc --stop-after parsing` absorbs invalid splices at ~ms; gate 2 is a
   full oracle run). Fallback when solc cannot parse the original
   (solc-rejects compile asymmetries): brace-aware line-chunk ddmin.
4. **Argument shrinking** — deterministic rank-decreasing candidates
   (ints → 0/1, strings → ""/"a", bytes → empty/halved, addresses → canonical
   labels, arrays → truncated).
5. **LLM simplify** — last, on the residual only (deletion cannot simplify
   expressions or narrow types); routed to the flash model tier.
6. **1-minimality verification** — exhaustive re-try of every single
   deletion and one-notch arg shrink; recorded as
   `minimality: {verified_one_minimal, residual_deletable, oracle_runs, stages}`.

Termination: every stage is budget-bounded and only accepts strictly smaller
candidates (span deletion shrinks the source; arg shrink strictly decreases
the rank). Cost model: each candidate costs ≤ 1 oracle run (≈1.8 s wall with
node boot; gate-1 rejects cost ~ms). Predicate caching is internal to the
reducer; `Executor.runs` stays an honest count of real oracle executions.

## The hunt loop as a pluggable generator

(~½ page.) The loop (generate → run → triage → minimize → dedup) treats the
spec generator as a plug-in: LLM generation, programmatic mutation, and LLM
batch mutation are interchangeable producers behind the same oracle
interface. Two-tier dedup: a cheap earliest-signature pre-check skips the
minimize spend for known witnesses; post-minimization merge via the
signature-set fingerprint (`agent/src/agent/loop.py`, `store.py`).
