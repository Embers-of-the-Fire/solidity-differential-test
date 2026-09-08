# AGENTS.md

Differential testing oracle for Solidity compilers: compiles the same source
with **solc** (EVM, deployed on `anvil`) and **solang** (Polkadot WASM,
deployed on `substrate-contracts-node`), replays identical transactions
on-chain, and reports behavioral divergence. See `oracle/README.md` for the
full spec/report schema — read it before touching comparison logic.

## Environment (NixOS, strict)

- All binaries come from the root flake devshell (`nix develop`, or direnv via
  `.envrc`): `solc`, `solang`, `anvil`, `substrate-contracts-node`, `uv`.
  `solang` and `substrate-contracts-node` are prebuilt upstream binaries
  wrapped in `flake.nix` (not in nixpkgs) — do not try to install them
  another way.
- Python deps: UV workspace rooted at the repo **root** (single `uv.lock` +
  `.venv`); `oracle/` is the only workspace member. Run `uv sync` once.
- Do **not** use pip, npm, or system package managers.

## Commands

```bash
# run an example (from repo root)
uv run --package solidity-diff-oracle solidity-diff-oracle \
    run oracle/examples/counter.json --md report.md

# tests (e2e: spawn both chain nodes; marked `slow`; require devshell binaries)
uv run --package solidity-diff-oracle pytest oracle/tests/
# single test: ... pytest oracle/tests/test_smoke.py -k counter

# lint/format (ruff is NOT in the devshell; config lives in oracle/pyproject.toml)
uvx ruff check oracle/src oracle/tests
uvx ruff format oracle/src oracle/tests
```

CLI exit code: `0` = chains agree (`PASS`), `1` = divergence found. A nonzero
exit is a *finding*, not a crash.

## Conventions that differ from defaults

- Ruff ignores `B904` and `E501` **intentionally** (see comment in
  `oracle/pyproject.toml`): chain adapters must catch *all* exceptions and
  record unexpected node/compiler behavior as data — never crash on it. Keep
  that pattern when editing `oracle/src/oracle/chains/`.
- `oracle/src/oracle/wasmutil.py` strips `soroban_*` exports from solang WASM
  (pallet-contracts rejects them); `scalemini.py` is a hand-rolled SCALE codec
  because `scalecodec`'s `ContractCallFlags` registry is stale. Do not
  "simplify" these away.
- Storage comparison defaults to `count` mode (count + zero-stripped values),
  not exact map equality, because EVM slots and Polkadot child-trie entries
  differ in layout/endianness. Block number/hash/timestamp and balances are
  recorded but **never** compared.
- Gas comparison is opt-in only; the EVM gas model and Substrate weights are
  incomparable.

## Layout

`oracle/src/oracle/` — `cli.py` (entrypoint `solidity-diff-oracle`),
`runner.py` (orchestration), `compilers.py` (solc/solang drivers),
`chains/{base,evm,polkadot}.py` (adapters + node process management),
`compare.py` (divergence classes), `spec.py` (JSON test-env schema).
`oracle/examples/` holds ready-to-run specs.
