# solidity-diff-agent

AI-in-the-loop bug hunter that drives the [differential oracle](../oracle/README.md)
(solc/EVM/anvil vs solang/Polkadot WASM/substrate-contracts-node) to discover
behavioral divergences between the two Solidity compiler implementations.

## How it works

A closed loop around the oracle (`spec JSON -> verdict + divergences[]`):

```
seed card -> LLM generates spec -> validate (+repair) -> oracle run ->
triage (rules + LLM) -> minimize (delta debugging) -> dedup -> findings DB
     ^                   |                                     |
     |                   '-> reflect: update hypothesis notebook per seed
     '------------------------ notebook feeds next generation <-'
```

- **Seeds** (`src/agent/seeds/*.json`): curated cards of suspected divergence
  areas (env vars, revert payloads, storage packing, int casts, ...).
  Coverage-first sampling rotates through the least-probed cards; seeds whose
  hypotheses are all resolved are softly deprioritized.
- **Hypotheses** (`hypotheses.py`, `reflect.py`): the loop's durable,
  cross-round memory. After **every** probe, a reflect call updates the
  per-seed notebook (`findings/hypotheses/<seed_id>.json`): add / confirm /
  refute / refine / retarget ops, validated deterministically. The next
  generation prompt for that seed carries its open hypotheses and their
  `next_probe` intents — rounds form a confirm/refute cycle instead of
  independent guesses. A PASS is evidence too: it can refute a suspected
  divergence or confirm agreement.
- **Generation** (`generator.py`): the LLM emits one spec JSON per round;
  a validate-and-repair loop (`llm.py`) enforces the schema before any
  expensive oracle run.
- **Execution** (`executor.py`): in-process `oracle.runner.run_spec`, parallel
  workers (nodes pick free ports and use ephemeral `--tmp` chains).
- **Triage** (`triage.py`): deterministic rules filter documented platform
  differences (env values, gas) and flag storage-`count` heuristic artifacts;
  everything else gets one LLM classification call
  (`known_semantic` / `oracle_artifact` / `bug_candidate` / `invalid_probe`).
- **Minimization** (`minimize.py`): greedy step pruning plus LLM-guided source
  shrinking, every candidate re-verified against the oracle.
- **Store** (`store.py`): append-only `findings.jsonl` + `probes.jsonl` +
  full reports, fingerprint dedup.

**LLM-call arithmetic per round**: 1 generate (up to 3 with repairs) + 0–1
triage (divergences not covered by rules) + 1 reflect + 0–3 minimize
(bug candidates only). Budget for `--llm-calls N` accordingly:
N ≈ 2–3 × rounds in the common case.

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

# restrict to specific seed areas
solidity-diff-agent hunt --seeds int-semantics,revert-reasons --rounds 10

# inspect deduplicated findings
solidity-diff-agent report --findings-dir findings/

# inspect accumulated per-seed hypotheses (the loop's durable knowledge)
solidity-diff-agent hypotheses --findings-dir findings/

# re-run one finding's reproducer (exit 1 = still diverging)
solidity-diff-agent replay <finding-id> --findings-dir findings/
```

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
- The oracle itself is imported read-only; no changes to comparison logic.
