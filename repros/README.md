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
