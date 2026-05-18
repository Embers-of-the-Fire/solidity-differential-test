# Fuzz Repros

These are small compiler-behavior repros found while running the Python mutational fuzzer against `solc` and `solang` with `--target evm`.

- `internal_fn_var_encode.sol`: `solc` emits a clean diagnostic, while `solang` panics with `This type cannot be encoded`.
- `internal_fn_packed_encode.sol`: `solc` emits a clean diagnostic, while `solang` panics with `This type cannot be encoded`.
- `rational_encode.sol`: `solc` emits a clean diagnostic, while `solang` panics with `Type should not exist in codegen`.
- `fixed_array_assignment.sol`: `solc` succeeds, while `solang` panics with `target not implemented`.
- `compound_assignment.sol`: `solc` succeeds, while `solang` panics with `target not implemented`.
- `complex_struct_array_compound_assignment.sol`: a higher-complexity nested case that combines memory fixed-array copying, struct assignment, storage writes, and compound assignment; `solc` succeeds, while `solang` panics with `target not implemented`.
- `tuple_struct_storage_swap.sol`: `solc` succeeds, while `solang` panics with `target not implemented` when tuple assignment writes through a struct-backed storage fixed array.
- `try_catch_initializer.sol`: `solc` succeeds, while `solang --target evm` panics in `src/codegen/statements/try_catch.rs:36:9` with `not implemented` when `try/catch` appears inside a state initializer helper.
- `base_constructor_free_function_arg.sol`: `solc` succeeds, while `solang` panics in `src/codegen/expression.rs:3339:80` with `no entry found for key` when a base-constructor argument is computed with a top-level free function.
- `evm_runtime_smoke.sol`: minimal Solang EVM compile-blocker case; `solc` emits EVM bytecode, while pinned Solang 0.3.4 panics with `target not implemented`, so `compare --runtime` should report runtime comparison as unavailable.
- `runtime_harness_smoke.sol`: solc-only runtime harness smoke case; it validates that the local `evm` runner can deploy bytecode extracted from `solc --bin`, independent of Solang.
- `runtime_constructor_panic.sol`: solc-only runtime failure smoke case; it compiles successfully but deployment executes `assert(false)`, so the EVM runner should report a runtime failure.

Current crash families observed so far:

- encoding rejection paths that should emit diagnostics instead panic in Solang codegen
- EVM backend assignment/update paths that still hit `target not implemented`, including simple and nested fixed-array/state-update cases and tuple writes into struct-backed storage arrays
- `try/catch` lowering in initializer-driven codegen still hits a separate `src/codegen/statements/try_catch.rs` panic path on EVM
- base-constructor argument lowering can hit a separate `src/codegen/expression.rs` map lookup panic when the argument is a top-level free-function call

You can check them directly with commands like:

```bash
solc --bin repros/fixed_array_assignment.sol
solang compile repros/fixed_array_assignment.sol --target evm
```

Solang EVM compile-blocker smoke check:

```bash
uv run solidity-diff-fuzz compare repros/evm_runtime_smoke.sol --runtime
```

Strict compile-and-runtime harness check:

```bash
uv run solidity-diff-fuzz harness-check repros/evm_runtime_smoke.sol
```

This command intentionally fails unless both the compile phase and runtime phase
can be compared across `solc` and `solang`. With the current pinned Solang 0.3.4
EVM target, it fails because Solang does not emit EVM bytecode.

For runtime behavior checks on EVM, pass ABI calldata to compare a deployed call
result after both creation bytecodes deploy successfully:

```bash
uv run solidity-diff-fuzz harness-check path/to/case.sol --calldata 0x3fb5c1cb
```

The runtime phase is a required differential phase for `harness-check`; if
Solang cannot emit executable EVM bytecode, the check fails rather than falling
back to compile-only output comparison.

Runtime-harness smoke check, independent of Solang:

```bash
uv run solidity-diff-fuzz runtime-smoke repros/runtime_harness_smoke.sol
```

Runtime-failure smoke check, independent of Solang:

```bash
uv run solidity-diff-fuzz runtime-smoke repros/runtime_constructor_panic.sol
```

Solang supported-target check for the pinned compiler:

```bash
uv run solidity-diff-fuzz target-check repros/runtime_harness_smoke.sol --solang-target polkadot
```

This compiles with both compilers and validates Solang's emitted `.wasm` with
`wasm-tools validate`. It is not a same-runtime comparison with `solc`, but it
does check whether the contract works far enough to produce a valid artifact for
a target that this Solang release officially supports.

The runtime harness gets `solc` bytecode from `solc --bin` stdout. When both
compilers eventually provide EVM bytecode, `compare --runtime` extracts Solang
bytecode from `.bin` artifacts and deploys both creation bytecodes with Geth's
`evm run --create`.

Generate an input-output oracle for a `uint256 -> uint256` function:

```bash
uv run solidity-diff-fuzz io-oracle \
  --expression 'a + 7' \
  --input 35 \
  --output /tmp/opencode/generated_io_oracle.sol
```

Then run both compiler outputs and compare runtime behavior:

```bash
uv run solidity-diff-fuzz runtime-diff /tmp/opencode/generated_io_oracle.sol \
  --solang-target polkadot \
  --calldata <printed calldata> \
  --expect <printed expect_evm> \
  --expect-solang <printed expect_solang_polkadot>
```
