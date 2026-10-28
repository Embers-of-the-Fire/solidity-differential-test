# solidity-diff-test

Differential bug hunting for Solidity compilers: the same contract is compiled
with solc (EVM) and solang (Polkadot WASM), identical transactions run on both
chains, and an AI agent searches for inputs where the two disagree.

## Prerequisites

- [Nix](https://nixos.org/) with flakes enabled — every tool (solc, solang,
  anvil, substrate-contracts-node, uv) comes from the project flake.

## Setup

```bash
nix develop     # or `direnv allow` once
uv sync         # python deps (once)
```

## Configure the model

Point the agent at any OpenAI-compatible server (llama.cpp, vLLM, Ollama, or a
hosted API). Either export the variables or put them in a `.env` file at the
repo root (loaded automatically; exported variables take precedence; the
`export` prefix is valid in both):

```bash
export AGENT_LLM_BASE_URL=http://127.0.0.1:8080/v1
export AGENT_LLM_MODEL=<model-name>
```

Optional:

```bash
export AGENT_LLM_MODEL_LIGHT=<cheap-model>   # used for mutate/minimize calls;
                                             # unset = same model for everything
export AGENT_LLM_API_KEY=<key>               # most local servers ignore it

# cost reporting only (USD per 1M tokens; defaults 0.0 = free/local)
export AGENT_LLM_PRICE_INPUT_PER_1M=0.0
export AGENT_LLM_PRICE_CACHED_INPUT_PER_1M=0.0
export AGENT_LLM_PRICE_OUTPUT_PER_1M=0.0
```

## Run the search

```bash
uv run --package solidity-diff-agent solidity-diff-agent hunt \
    --rounds 20 --llm-calls 100 --oracle-runs 200 \
    --findings-dir findings/
```

Budgets are hard stops — the search ends when any of them is hit. Progress is
printed as it goes; everything it finds lands in `findings/`.

## See what it found

```bash
# deduplicated list of divergences
uv run --package solidity-diff-agent solidity-diff-agent \
    report --findings-dir findings/

# token usage and cost
uv run --package solidity-diff-agent solidity-diff-agent \
    cost --findings-dir findings/

# re-run a finding's reproducer (exit 1 = still diverging)
uv run --package solidity-diff-agent solidity-diff-agent \
    replay <finding-id> --findings-dir findings/
```

Each finding is a minimized, self-contained spec that reproduces the
divergence, with the oracle report showing exactly where the two chains
disagreed.
