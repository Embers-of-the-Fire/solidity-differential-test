# solidity-diff-agent

AI-in-the-loop bug hunter that drives the [differential oracle](../oracle/README.md)
(solc/EVM/anvil vs solang/Polkadot WASM/substrate-contracts-node) to discover
behavioral divergences between the two Solidity compiler implementations.

## How it works

A feedback-driven fuzzing loop around the oracle
(`spec JSON -> verdict + divergences[]`). Each round is one of two kinds:

```
                    pick seed card (coverage-first)
                              |
              +--- p_mutate --+-- (1 - p_mutate) ---+
              |                                  |
   GENERATION round                    MUTATION round
   LLM generates spec from        corpus parent (roulette on energy)
   seed + notebook + memory       -> k programmatic mutants (free)
              |                     + 1 LLM call proposing n source mutants
              |                     (invalid discarded, counted)
              +----------+----------+
                         v
              oracle run (batch, parallel)
                         v
        triage (deterministic rules -> LLM only if uncovered)
                         v
   corpus admission + energy feedback on the parent
                         v
   reflect (notebook update) -> minimize -> dedup -> findings DB
```

- **Seeds** (`src/agent/seeds/*.json`, or `--seeds-dir` for a frozen corpus):
  cards describing suspected divergence areas. Coverage-first sampling rotates
  through the least-probed cards; seeds whose hypotheses are all resolved are
  softly deprioritized. Topic-level scheduling only — input-level scheduling
  is the corpus's job.
- **Corpus** (`corpus.py`): admitted specs with lineage (`parent_id`,
  `origin`) and per-parent offspring stats. Admission rule: divergence (not a
  known fingerprint), novel divergence-kind combination for the seed, seed
  bootstrap entries, or everything when `admission=off` (evaluation control).
  Parent selection is fitness-proportional on `energy`: +1 divergent
  offspring, +2 novel, −0.1 invalid/duplicate, floor 0.1, ×0.95 decay/round.
- **Mutation** (`mutate.py`): two operator families. Programmatic
  sequence-level operators (shuffle calls, duplicate step, perturb args to
  boundary values, swap sender, insert read-back query, zero value) are
  JSON-level, valid by construction, zero LLM cost. LLM source-level mutation
  is one batched call proposing `llm_mutants_per_round` mutants from a
  mutation menu; invalid mutants are discarded without repair — the discard
  rate is an evaluation datum, not a failure.
- **Hypotheses** (`hypotheses.py`, `reflect.py`): the loop's durable,
  cross-round memory — the semantic feedback signal standing in for coverage
  (which is incomparable across EVM and WASM backends). After each probe a
  reflect call updates the per-seed notebook
  (`findings/hypotheses/<seed_id>.json`): add / confirm / refute / refine /
  retarget ops, validated deterministically. `reflect=never` is the feedback
  ablation axis.
- **Generation** (`generator.py`): from-scratch spec generation for empty or
  under-explored corpus partitions; a validate-and-repair loop (`llm.py`)
  enforces the schema before any oracle run.
- **Execution** (`executor.py`): in-process `oracle.runner.run_spec`;
  mutation batches go through `run_many` on a thread pool (nodes pick free
  ports and use ephemeral `--tmp` chains).
- **Triage** (`triage.py`): deterministic rules filter documented platform
  differences and mechanically-decidable oracle artifacts (the oracle's
  `compare.py` suppresses the recurring ones at the source; see
  `docs/llm-diff.md`); everything else gets one LLM classification call
  (`known_semantic` / `oracle_artifact` / `bug_candidate` / `invalid_probe`).
- **Minimization** (`minimize.py`): greedy step pruning plus LLM-guided source
  shrinking, every candidate re-verified against the oracle; known
  fingerprints are skipped before any LLM spend.
- **Stop policy** (`stop.py`): owned by the caller (CLI or eval harness), not
  the loop. Stops: `round_limit`, `oracle_budget`, `llm_budget`,
  `saturation` (K rounds with no new finding, divergence kind, or hypothesis
  transition).
- **Store** (`store.py`): append-only `findings.jsonl` + `probes.jsonl` +
  `corpus.jsonl` + full reports, fingerprint dedup.

**LLM-call arithmetic**: a generation round costs ~2–3 calls (1 generate +
0–1 triage + 0–1 reflect, + minimize on candidates). A mutation round costs
1 batch-mutate call + (triage + reflect) **per divergent mutant** + minimize
per new candidate — variable, and it scales with batch size. This is why
cross-configuration comparisons budget on **oracle runs**, not LLM calls or
rounds (the eval harness enforces this; see below).

## Configuration

The LLM endpoint is a **placeholder by default** — the first run fails fast
until you point the agent at your local OpenAI-compatible server:

```bash
export AGENT_LLM_BASE_URL=http://127.0.0.1:8080/v1   # llama.cpp / vLLM / Ollama
export AGENT_LLM_MODEL=<your-model-name>
export AGENT_LLM_API_KEY=local                        # usually ignored locally
```

Optional token prices (USD per 1M tokens, all default `0.0` for local
inference) used for the cost trace:

```bash
export AGENT_LLM_PRICE_INPUT_PER_1M=0.0          # uncached prompt tokens
export AGENT_LLM_PRICE_CACHED_INPUT_PER_1M=0.0   # cached prompt tokens (default: input price)
export AGENT_LLM_PRICE_OUTPUT_PER_1M=0.0         # completion tokens
```

Loop knobs (`AgentConfig`, settable via `load_config` or as eval-matrix
overrides; the ablation axes are marked):

| knob | default | meaning |
|---|---|---|
| `p_mutate` | 0.7 | probability a round mutates a corpus parent instead of generating from scratch — **ablation: 0.0 = generation-only baseline** |
| `prog_mutants_per_round` | 4 | free programmatic mutants per mutation round |
| `llm_mutants_per_round` | 4 | mutants requested in the single batch LLM call (0 = programmatic-only) |
| `prog_ops_per_mutant` | 2 | operator applications per programmatic mutant |
| `reflect` | `always` | notebook feedback per probe — **ablation: `never`** |
| `admission` | `on` | corpus admission rule — **ablation: `off` admits everything (random-restart control)** |
| `saturation_window` | 10 | K for the saturation stop |
| `seeds_dir` | packaged | swap in a frozen seed corpus (e.g. `agent/seeds_derived/`) |

## Cost & time tracing

Every chat-completion call (including retried/failed attempts and repair-loop
iterations) is appended to `findings/llm_usage.jsonl` — one JSON object per
line with:

- `ts`, `stage` (`generate` / `triage` / `reflect` / `minimize`), `attempt`
  (repair-loop index), `model`, `temperature`
- `latency_ms`
- `prompt_tokens`, `cached_prompt_tokens`, `completion_tokens`,
  `total_tokens`, `cost_usd`
- `usage_raw`: the server's `usage` object verbatim, so provider-specific
  fields are preserved. Cached-token splits are only visible when the server
  reports them (`usage.prompt_tokens_details.cached_tokens` — OpenAI and vLLM
  do; llama.cpp typically does not, in which case `cached_prompt_tokens` is
  null and all input tokens are billed at the full input rate).
- `error`: set for failed attempts (tokens unknown → `cost_usd` is null)

Per-probe phase timing (`generate_ms`, `oracle_ms`, `triage_ms`,
`reflect_ms`, `minimize_ms`, `round_ms`) and per-round token/cost deltas are
stored in `probes.jsonl`; accepted findings carry the same (cost-to-discover).
The oracle report itself carries its own elapsed-time trace
(`timing.*` in the report JSON — see the oracle README).

Aggregates:

```bash
solidity-diff-agent cost --findings-dir findings/   # totals, per-stage, per-seed
```

## Usage (from the repo root, inside the devshell)

```bash
uv sync

# run the loop (budgets are hard stops; every oracle run spawns both nodes)
uv run --package solidity-diff-agent solidity-diff-agent hunt \
    --rounds 20 --llm-calls 100 --oracle-runs 200 --parallel 4 \
    --findings-dir findings/

# generation-only baseline (no mutation), or stop after 10 signal-free rounds
solidity-diff-agent hunt --p-mutate 0.0 --saturation-window 10

# restrict to specific seed areas / a frozen seed corpus
solidity-diff-agent hunt --seeds int-semantics,revert-reasons --rounds 10
solidity-diff-agent hunt --seeds-dir agent/seeds_derived/

# inspect deduplicated findings
solidity-diff-agent report --findings-dir findings/

# inspect accumulated per-seed hypotheses (the loop's durable knowledge)
solidity-diff-agent hypotheses --findings-dir findings/

# re-run one finding's reproducer (exit 1 = still diverging)
solidity-diff-agent replay <finding-id> --findings-dir findings/
```

## Evaluation (ablation matrix)

`solidity-diff-agent eval` runs configurations × repeats under a common
budget. The fair budget axis is **oracle runs** (configs consume LLM calls
differently); LLM calls and wall clock are reported alongside.

```bash
solidity-diff-agent eval --config matrix.json --out-root eval/run1
```

Matrix file schema:

```json
{
  "budget": {"oracle_runs": 300, "llm_calls": 200, "saturation_window": 10},
  "repeats": 5,
  "configs": [
    {"name": "full",      "overrides": {}},
    {"name": "no-mutate", "overrides": {"p_mutate": 0.0}},
    {"name": "no-reflect","overrides": {"reflect": "never"}},
    {"name": "no-admit",  "overrides": {"admission": "off"}}
  ]
}
```

`overrides` are `AgentConfig` fields; budgets and `findings_dir` are owned by
the harness. Each run gets a fresh findings dir and a deterministic rng seed
(hash of config name + repeat); a crashed run is recorded as `failed` in
`run.json`, never silently dropped. Output: `summary.json` + `runs.csv`,
`origins.csv`, `saturation.csv` — per-run metrics
(`findings_per_100_oracle_runs`, `llm_calls_per_finding`,
`mutant_discard_rate`, `corpus_admission_rate`, saturation series) aggregated
as median/min/max across repeats.

## Offline seed-corpus pipeline

Historical compiler bugs are distilled into seed cards **offline** — no bug
mining happens during a hunt (`agent/tools/`):

```bash
# 1. refresh the committed raw cache (uses the `gh` CLI for auth)
uv run --package solidity-diff-agent python agent/tools/fetch_bug_corpus.py

# 2. distill into candidate cards (one LLM call per bug report)
uv run --package solidity-diff-agent python agent/tools/distill_seeds.py \
    --dry-run          # list records first
uv run --package solidity-diff-agent python agent/tools/distill_seeds.py \
    --limit 10
```

Sources: solang issues labelled `bug`, merged fix PRs, CHANGELOG "Fixed"
entries, and solc's `docs/bugs.json`. Distillation writes review-ready
candidates under `agent/data/bug_corpus/candidates/`; a **human gate** copies
accepted cards into `agent/seeds_derived/` (the frozen corpus) and accepted
intentional differences into `agent/src/agent/data/known_differences.json`.

## Tests

```bash
# unit tests (no chain nodes needed; LLM is mocked)
uv run --package solidity-diff-agent pytest agent/tests/ -m "not slow"

# e2e smoke: real oracle run with a canned LLM (needs devshell binaries)
uv run --package solidity-diff-agent pytest agent/tests/
```

## Guardrails

- LLM output is only ever parsed as JSON; generated Solidity reaches
  `solc`/`solang` in temp workdirs — the same trust level as hand-written specs.
- Hard budgets on LLM calls and oracle runs; all prompts/responses land in
  `probes.jsonl`/`findings.jsonl` for reproducibility.
- Oracle comparison logic changes are reviewed and documented
  (`docs/llm-diff.md`); artifact suppressions never drop raw data —
  suppressed values stay recorded in the report.
