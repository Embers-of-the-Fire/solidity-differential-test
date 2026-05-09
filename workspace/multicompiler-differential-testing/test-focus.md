# Multiplatform Multicompiler Differential Test Focus

## Motivation

Existing Solidity compiler-testing work mostly focuses on `solc`, Solidity-specific mutation, or EVM-oriented compiler behavior. For this project, the better model is broader multicompiler differential testing: GCC vs Clang/LLVM for C/C++, or `rustc` with LLVM against alternative Rust backends such as GCC/Cranelift-style code generation.

The central question is therefore not only whether one Solidity compiler has bugs, but whether independent implementations of the same Solidity semantics preserve the same observable behavior across frontends, lowering layers, and targets.

## Lessons From Other Multicompiler Work

GCC/Clang/LLVM-style differential testing usually follows this pattern:

- Generate or mutate programs that should have defined behavior.
- Compile the same source with multiple compilers, versions, optimization levels, or backends.
- Compare stable observable outcomes, not raw diagnostic text, IR, or binary layout.
- Treat compiler crashes, acceptance mismatches, and runtime output mismatches as high-value findings.
- Minimize failing cases so that the responsible language feature or lowering path is clear.

Csmith is especially relevant because its value comes from avoiding undefined and unspecified behavior. The generator does not merely produce syntactically valid C; it tries to produce programs whose behavior is defined by the standard, so disagreement between GCC and LLVM is more likely to indicate a compiler bug.

EMI-style work is also relevant. Instead of always generating from scratch, it starts from a valid program and creates variants that are equivalent modulo selected inputs. This gives a larger test space while keeping an oracle: equivalent variants should behave the same.

Rust compiler fuzzing adds another lesson. RustSmith/Rustlantis-style approaches must generate well-typed programs that respect language constraints such as ownership, borrowing, lifetimes, and backend-relevant layout behavior. For Solidity, the analogous constraints are type correctness, `memory`/`storage`/`calldata` placement, ABI shape, visibility, mutability, inheritance, and target support.

## Solidity Analogy

For this project, `solc` vs `solang` should be treated like GCC vs Clang/LLVM: two independent implementations of the same language, with potentially different frontends, semantic lowering, optimizer assumptions, and backend support.

The closest Rust analogy is comparing `rustc` with LLVM codegen against a different backend. `solang --target evm` is not just a second command-line tool; it is a separate compiler implementation that may disagree with `solc` in frontend acceptance, ABI lowering, storage layout, code generation, or target-specific behavior.

This means the test focus should be:

- Same Solidity source.
- Same intended language semantics.
- Multiple compiler implementations or targets.
- Stable comparison oracle.
- Bias toward cases where disagreement is likely to be a real compiler issue, not an unsupported-feature artifact.

## Primary Test Focus

The current system should remain compile-focused first, because compile outcomes are easy to collect and already reveal useful `solang` EVM backend/codegen failures.

The primary focus should be ordered as follows:

- Compiler crash mismatch: one compiler panics or hits an internal error while the other reports a normal diagnostic or succeeds.
- Acceptance mismatch: one compiler accepts a Solidity program that the other rejects, after filtering known unsupported target features.
- Diagnostic-class mismatch: both reject, but one rejection class suggests an internal compiler failure or misclassification.
- Runtime behavior mismatch: future extension for cases that both compilers successfully compile and whose behavior is deterministic under a controlled EVM harness.

Raw artifact differences should not be a main oracle. GCC/LLVM work does not normally classify different binary bytes as bugs by itself; it asks whether the compiled program behaves differently. Similarly, Solidity bytecode, metadata, diagnostics, and generated artifact names may differ without indicating a semantic bug.

## Test Case Selection

Test cases should be selected like Csmith or RustSmith cases: small, valid, deterministic, and easy to minimize. The goal is not maximum Solidity syntax coverage; the goal is high signal-to-noise differential behavior.

High-priority case classes:

- Shared-success seeds: inputs expected to compile on both `solc` and `solang --target evm`. These are the best candidates for future runtime comparison.
- Defined-behavior runtime seeds: cases that avoid unspecified evaluation assumptions, external chain state, gas-boundary behavior, unsupported builtins, and complex deployment dependencies.
- Backend-comparison seeds: cases where the frontend semantics are clear but lowering/codegen is risky, such as storage layout, ABI encoding, aggregate copy, control-flow lowering, and integer-width conversion.
- Known-bug neighborhood variants: small mutations around previously observed `solang` failures, such as internal-function ABI encoding, rational literal encoding, state initializers, fixed-array assignment, tuple assignment into storage, and compound assignment.
- Feature-interaction cases: combinations of two to four risky features, for example struct plus fixed array plus storage write plus compound assignment.
- Valid diagnostic cases: intentionally invalid but well-scoped inputs where a normal compiler should emit a diagnostic, useful for finding panic-vs-diagnostic mismatches.

Low-priority or noisy case classes:

- Programs that mostly exercise target-specific unsupported features.
- Programs whose only observable difference is raw diagnostic wording.
- Large random contracts that are hard to reduce.
- Cases depending on external contracts, chain state, gas limits, timestamps, block fields, or deployment order unless the runtime harness controls them explicitly.
- Inputs where Solidity semantics are ambiguous or where both compilers are allowed to choose different behavior.

## Test Case Generation

The generator should combine constrained generation and mutation rather than use unconstrained random Solidity.

Csmith-style generation for Solidity:

- Generate complete valid contracts from typed templates.
- Enforce Solidity-level defined behavior.
- Bound loops, array sizes, and state-space growth.
- Avoid target-unsupported features unless the goal is specifically diagnostic robustness.
- Track feature tags for each generated case.

EMI-style mutation for Solidity:

- Start from a seed accepted by both compilers.
- Insert dead branches, equivalent helper calls, equivalent tuple destructuring, or local variable materialization.
- Mutate only in ways that preserve behavior for selected inputs.
- Compare the original and mutated variants across both compilers.

RustSmith/Rustlantis-style typed generation for Solidity:

- Maintain explicit type and data-location constraints.
- Treat `memory`, `storage`, and `calldata` like first-class generator state.
- Track ABI-visible function signatures separately from internal helper structure.
- Generate inheritance, modifiers, structs, arrays, and mappings only when their interactions remain interpretable.

Backend-focused mutation:

- Vary integer widths while preserving explicit casts.
- Vary fixed-array lengths and struct nesting depth.
- Move values between `memory`, `storage`, and `calldata` when legal.
- Switch between tuple assignment, temporary variables, and direct assignment.
- Switch between `abi.encode` and `abi.encodePacked` for known edge types.
- Change constructor/state-initializer expression shapes while keeping semantics simple.

## Mapping to the Current Repository

The current repository already has two useful generation paths.

`working/scripts/generate_seeds.py` is the deterministic seed corpus path. It is useful for regression tests, interpretable examples, and future runtime oracle development. Its current seeds cover tuple swap, short-circuit side effects, compound assignment, constructor state flow, mapping getter, ternary type join, struct roundtrip, storage array push/pop, fixed-array assignment, modifier ordering, inheritance/super, nested loop, and bytes/hash roundtrip.

`src/solidity_diff_fuzz/` is the template/spec mutation path. It generates programs from Jinja2 snippets and mutates operators, integer widths, state snippets, function snippets, literals, comparison operators, encode modes, and rational literals. This is the better path for broader search and for finding new crash, acceptance, and diagnostic-class mismatches.

The template set already emphasizes good backend-risk areas:

- Aggregate copy: fixed-size memory arrays, struct roundtrip, storage-backed struct arrays.
- Assignment lowering: tuple assignment, compound assignment, storage update.
- Initialization and control flow: constructor/state initializer, modifier ordering, short-circuit, nested loop.
- ABI and type edges: public mapping getter, `abi.encode`, `abi.encodePacked`, internal function values, rational literals, integer-width joins.
- Memory/calldata behavior: bytes copy, hashing, calldata-to-memory conversion.

## Recommended Experiment Direction

The near-term focus should be `solc` vs `solang --target evm`, because EVM gives the cleanest shared platform and avoids much of the noise from non-EVM target support gaps.

Recommended workflow:

- Generate or mutate a small Solidity case with feature tags.
- Compile with both compilers.
- Classify the outcome as crash, acceptance mismatch, diagnostic-class mismatch, shared success, or unsupported noise.
- Save new unique crash and mismatch signatures.
- Minimize high-value mismatches into `repros/`.
- Feed minimized repro patterns back into generator weights.

Multiplatform testing should be a second phase. A case should first be shared-success on EVM, then projected to other `solang` targets. For non-EVM targets, the most valuable findings are target-independent semantic failures and internal compiler failures, not simple unsupported-feature reports.

Runtime comparison should also be staged. It should start only from small shared-success seeds with predictable inputs and outputs, such as tuple swap, compound assignment, modifier ordering, fixed-array copy, and bytes/hash roundtrip.
