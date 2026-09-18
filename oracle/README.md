# solidity-diff-oracle

An **on-chain differential testing oracle** for Solidity compilers. It compiles
the same Solidity source with **solc** (EVM target) and **solang** (Polkadot /
pallet-contracts WASM target), deploys both artifacts on real local chain
nodes, replays an identical sequence of transactions against both, and reports
any divergence in observable behavior.

| Side | Compiler | Artifact | Chain |
|------|----------|----------|-------|
| A ("evm") | `solc` | EVM bytecode | `anvil` (Foundry) local EVM node |
| B ("polkadot") | `solang --target polkadot` | WASM (pallet-contracts) | `substrate-contracts-node` |

Everything executes **on-chain**: each `call` step is a real, committed
transaction on both nodes. Read-only `query` steps are dry-runs
(`eth_call` on EVM, `ContractsApi.call` runtime API on Polkadot).

## Layout

```
oracle/
├── pyproject.toml          # UV project (web3, substrate-interface)
├── src/oracle/
│   ├── cli.py              # `solidity-diff-oracle run <spec.json>`
│   ├── spec.py             # test-environment spec schema + validation
│   ├── schema.py           # block-state schema + outcome types
│   ├── compilers.py        # solc / solang drivers
│   ├── wasmutil.py         # strips solang's soroban_* exports (pallet-contracts compat)
│   ├── scalemini.py        # minimal SCALE codec for ContractsApi.call
│   ├── accounts.py         # well-known account labels ($deployer/$alice/...)
│   ├── chains/
│   │   ├── base.py         # ChainAdapter interface + node process management
│   │   ├── evm.py          # anvil adapter
│   │   └── polkadot.py     # substrate-contracts-node adapter
│   ├── runner.py           # orchestration: compile -> deploy -> steps
│   ├── compare.py          # oracle comparator + divergence classes
│   └── report.py           # JSON + Markdown reports
├── examples/               # ready-to-run test environments
└── tests/                  # pytest smoke tests (spawn both nodes)
```

## Quick start

All binaries are provided by the flake devshell at the repo root
(`solc`, `solang`, `anvil`, `substrate-contracts-node`, `uv`). Python
dependencies are managed by a UV workspace rooted at the repo root
(`oracle` is a workspace member; single `uv.lock` + `.venv` at the root):

```bash
nix develop                  # enter the devshell (repo root)
uv sync                      # install workspace python deps (UV)
uv run --package solidity-diff-oracle solidity-diff-oracle \
    run oracle/examples/counter.json --md report.md
```

Running from inside `oracle/` works too (`uv` walks up to the workspace root):
`cd oracle && uv run solidity-diff-oracle run examples/counter.json`.

Exit code is `0` when the two chains behave identically (verdict `PASS`),
`1` when a divergence is found.

Run the tests:

```bash
uv run --package solidity-diff-oracle pytest oracle/tests/   # or: cd oracle && uv run pytest tests/
```

## Test-environment spec

A test environment is a single JSON file:

```json
{
  "name": "counter-basic",
  "source_file": "counter.sol",            // or inline: "solidity": "contract C {...}"
  "contract": "counter",
  "constructor": { "args": [7] },          // "name" optional (default: solang "new")
  "solc":   { "optimizer": false, "optimizer_runs": 200, "evm_version": "..." },
  "solang": { "opt_level": "default" },    // none | less | default | aggressive
  "oracle": {
    "storage": "count",                    // count | exact | off
    "events": true,
    "revert_reasons": true,
    "gas": false
  },
  "steps": [
    { "action": "query", "function": "count" },
    { "action": "call", "function": "inc", "args": [5], "sender": "alice", "value": 0 }
  ]
}
```

Step fields:

- `action`: `call` = committed transaction (state changes, events, storage are
  recorded; a dry run is also performed to capture the return value);
  `query` = read-only dry run, no block is produced.
- `function`: Solidity function name (overloads are disambiguated by arity).
- `args`: positional JSON arguments. `"$label"` resolves to a well-known
  account address (`$deployer`, `$alice`, `$bob`, `$charlie`, `$contract`).
  `0x..` strings become bytes for `bytes*` params.
- `sender`: account label (default `deployer`).
- `value`: native units sent along (wei on EVM, planck on Polkadot).

## Block-state schema

Each chain adapter fills in the same oracle-defined snapshot after every
committed transaction:

```json
{
  "chain": "evm",
  "block":    { "number": 3, "hash": "0x..", "timestamp": 1730000000 },
  "contract": { "address": "0x..", "balance": "1000000000000", "nonce": 0 },
  "storage":  { "0x<slot-or-key>": "0x<value>" }
}
```

Notes per chain:

- **EVM** — storage is the *cumulative* set of slots ever written by the
  contract (via `debug_traceTransaction` with `prestateTracer`/`diffMode`;
  anvil does not implement `debug_storageRangeAt`). Slot keys are 32-byte.
- **Polkadot** — storage is the *full* contract child-trie
  (`Contracts.ContractInfoOf.trie_id` -> `childstate_getKeys`/`getStorage`).
  Keys/values are raw bytes (SCALE-encoded values).

Block metadata (number/hash/timestamp) and balances are recorded for
traceability but are **never** part of the oracle comparison: chains differ in
units, fee models and block cadence by design.

## What the oracle compares

For every step, both sides are reduced to a comparable form and checked:

| Signal | Source | Compared |
|--------|--------|----------|
| compile success | solc / solang exit + diagnostics | always (`COMPILE_ASYMMETRY`) |
| deploy status | deploy tx receipt / instantiate extrinsic | always (`DEPLOY_MISMATCH`) |
| dry-run status | `eth_call` / `ContractsApi.call` | always (`STATUS_MISMATCH`) |
| return value | ABI-decoded outputs / SCALE-decoded per metadata | on success (`RETURN_MISMATCH`) |
| revert reason | `Error(string)`/`Panic(uint256)` / solang `0x08c379a0`+SCALE | on revert (`REASON_MISMATCH`, opt-out) |
| tx status | receipt.status / extrinsic success | always (`TX_STATUS_MISMATCH`) |
| events | decoded logs / decoded `ContractEmitted` | opt-out (`EVENT_MISMATCH`) |
| storage | snapshot maps | `count`/`exact`/`off` (`STORAGE_MISMATCH`) |
| gas | receipt gasUsed / weight ref_time | opt-in only (`GAS_MISMATCH`) |

Values are normalized before comparison: bytes become `0x` hex, big integers
stay exact, and known addresses are reverse-mapped to their `$labels` so an
address returned on both chains compares equal regardless of the 20-byte
(EVM) vs 32-byte (AccountId32) representation.

### Storage comparison modes

- `count` (default): compare the number of non-zero storage entries plus the
  sorted list of zero-stripped values. Robust to the different storage layouts
  and endianness of the two targets; may raise false positives for contracts
  relying on tight slot packing or multi-byte little-endian values.
- `exact`: raw key->value map equality (only meaningful for same-target setups).
- `off`: storage is recorded in the report but not compared.

## Divergence kinds

`COMPILE_ASYMMETRY`, `DEPLOY_MISMATCH`, `STATUS_MISMATCH`, `RETURN_MISMATCH`,
`REASON_MISMATCH`, `TX_STATUS_MISMATCH`, `EVENT_MISMATCH`, `STORAGE_MISMATCH`,
`GAS_MISMATCH` (opt-in).

## Report

- JSON (always written; default `<workdir>/report.json`): full fidelity —
  per-step dry-run outcome, tx outcome, and chain state snapshot for both
  chains, plus the flat divergence list and the verdict.
- Markdown (`--md report.md`): summary tables for humans.

### Timing trace

Every report carries an elapsed-time trace (wall-clock milliseconds, plus a
UTC `started_at` timestamp):

- `timing.total_ms`, `timing.started_at`, `timing.started_epoch`,
  `timing.nodes.<chain>.{start_ms, stop_ms}`
- `compile.<solc|solang>.elapsed_ms`, `deploy.<chain>.elapsed_ms`
- per step: `steps[i].timing.<chain>.{dry_run_ms, tx_ms, snapshot_ms}` and
  `steps[i].timing.<chain>_total_ms`

Timing is recorded for traceability and cost analysis only; it is **never**
part of the oracle comparison (same rule as block metadata and balances).

## Known limitations / intentional quirks

- solang v0.3.5 emits `soroban_*` function exports even for the Polkadot
  target; pallet-contracts rejects those, so the oracle strips non-`deploy`/
  `call` function exports from the WASM before upload (see `wasmutil.py`).
- `scalecodec`'s `ContractCallFlags` registry is stale (no REVERT bit), so the
  Polkadot dry-run uses a hand-rolled SCALE codec for `ContractsApi.call`
  (see `scalemini.py`); revert = raw flag bit 0.
- Gas is never compared by default: the EVM gas model and the Substrate weight
  model are incomparable.
- `value` uses each chain's smallest native unit; there is no exchange-rate
  mapping (chains are independent dev networks).
