# Runtime Differential Infrastructure Summary

## Goal

The implemented infrastructure explores a practical way to compare runtime behavior between `solc` and the pinned Solang 0.3.4 compiler in this repository.

The intended workflow is:

1. Take one Solidity source file or generated input-output oracle.
2. Compile it with `solc`.
3. Compile it with `solang`.
4. Execute both compiler outputs.
5. Compare runtime behavior at the logical input-output level.

## Toolchain Reality

The pinned Solang 0.3.4 binary does not provide a working EVM backend. `solang compile --target evm` panics with `target not implemented`, so a same-EVM runtime comparison is not available with the current pinned compiler.

To still execute both outputs, the current harness uses a cross-target strategy:

- `solc` output runs as EVM bytecode through Geth's `evm` runner.
- `solang --target polkadot` output runs as Wasm through a small Python Wasmtime host-stub runner that implements the minimal `seal0` imports needed by simple pure-call contracts.

This is not a full blockchain node simulation. It is a lightweight runtime oracle for small generated contracts with simple pure `uint256 -> uint256` behavior.

## Added Infrastructure

### Runtime Comparison Commands

The CLI now includes several commands:

- `compare`: compile both compilers and report normalized compiler/artifact differences.
- `harness-check`: require both compile-time and runtime comparison to be available for EVM-style comparison.
- `runtime-smoke`: validate the EVM runner using `solc` bytecode.
- `target-check`: compile Solang supported targets and validate emitted Wasm structure with `wasm-tools validate`.
- `runtime-diff`: run both compiler outputs and compare against expected runtime output.
- `io-oracle`: generate a simple Solidity input-output oracle contract.
- `io-diff`: generate an oracle and run both `solc` and `solang` outputs, comparing logical behavior.

### Runtime Backends

Implemented runtime components:

- EVM runner wrapper around Geth `evm run --create` and `evm run --input`.
- Runtime failure classification for EVM observations, including Solidity `Panic(uint256)` selector detection.
- Polkadot Wasm host-stub runner using Python `wasmtime`.
- Minimal `seal0` host functions for simple Solang Polkadot contracts:
  - `seal0.input`
  - `seal0.value_transferred`
  - `seal0.debug_message`
  - `seal0.seal_return`

### IO Oracle Generator

The `io-oracle` / `io-diff` path generates contracts like:

```solidity
contract GeneratedIoOracle {
    function run(uint256 a) external pure returns (uint256) {
        return a + 7;
    }
}
```

It handles target-specific calldata and expected-return encoding internally:

- EVM uses standard ABI big-endian `uint256` words.
- The Solang Polkadot host-stub path currently observes little-endian `uint256` words.

The command compares logical values instead of raw bytes, so ABI byte layout differences are not treated as behavioral mismatches when both sides compute the same value.

Example:

```bash
nix develop -c uv run solidity-diff-fuzz io-diff \
  --expression 'a + 7' \
  --input 35 \
  --solang-target polkadot
```

Expected result:

```text
Runtime differential test: pass
Differences:
- none
```

The report still prints per-side raw return bytes for debugging, but they are not considered semantic differences when both decode to the same logical value.

## Added Files

Key Python modules:

- `src/solidity_diff_fuzz/compare.py`
- `src/solidity_diff_fuzz/runtime.py`
- `src/solidity_diff_fuzz/diff_test.py`
- `src/solidity_diff_fuzz/io_oracle.py`
- `src/solidity_diff_fuzz/polkadot_runtime.py`
- `src/solidity_diff_fuzz/target.py`

Smoke repros:

- `repros/evm_runtime_smoke.sol`
- `repros/runtime_harness_smoke.sol`
- `repros/runtime_constructor_panic.sol`

Research/report note:

- `workspace/runtime-environment-research/runtime-environment-report.md`

## Nix and Python Dependencies

Added Nix dev-shell tools:

- `go-ethereum` for the `evm` runner.
- `wasm-tools` for Wasm validation.

Added Python dependencies through `uv`:

- `wasmtime` for executing Solang Polkadot Wasm with host stubs.
- `eth-utils` and `pycryptodome` for Keccak function selector generation.

## Validation Performed

Before committing the infrastructure, the following checks passed:

```bash
uv run pytest
nix develop -c ruff check src/solidity_diff_fuzz
nix develop -c statix check flake.nix
```

The full repository-wide Ruff check still reports pre-existing documented issues in `working/scripts/classify_mismatches.py` and `working/scripts/generate_seeds.py`.

## Current Limitations

The Polkadot runner is intentionally minimal. It is suitable for small pure calls, not full Substrate contracts execution.

Known limitations:

- No storage persistence across calls.
- No events/log decoding.
- No balance/account model.
- No full pallet-contracts gas/account semantics.
- No constructor state model beyond what the generated simple pure contracts require.
- Solana execution is not implemented; `solana-cli` did not build cleanly in the pinned Nix environment during probing.

## Practical Meaning

The infrastructure now supports a useful first runtime oracle:

- Generate small deterministic functions.
- Run `solc` EVM output.
- Run Solang Polkadot Wasm output.
- Compare logical input-output behavior.

This is enough to search for simple runtime semantic mismatches while avoiding the unsupported Solang EVM backend.

Future work should expand the Polkadot runtime host or replace it with a real pallet-contracts node/test runtime so that stateful contracts, events, and richer target behavior can be compared.
