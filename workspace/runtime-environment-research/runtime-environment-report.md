# Runtime Environment Options for `solc` vs `solang` Differential Testing

## Executive Summary

The most practical long-term runtime oracle for this repository is a controlled EVM execution harness fed by `solc` bytecode and `solang --target evm` bytecode. It is the only option that can plausibly run both compilers' outputs in the same virtual machine and compare the same machine-observable events: call success, return bytes, revert data, logs, storage reads, storage roots, and gas-independent traces.

A local Nix trial found an important blocker: the pinned Solang 0.3.4 binary in this repository advertises only `solana` and `polkadot` in `solang compile --help`, and `solang compile --target evm` panics with `not implemented: target not implemented` when asked to emit binary output for a small deployable contract. Therefore, EVM remains the right shared-runtime design target, but the current pinned Solang cannot yet complete the full `solc` vs `solang` EVM runtime loop without changing the Solang version/build or adding a different EVM-capable Solang artifact.

The recommended path is therefore staged:

1. Keep the current compile-time oracle as the default high-throughput filter.
2. Add a small EVM runtime harness for cases where both compilers accept the source.
3. Compare ABI-level function return data first, then extend to storage snapshots, logs, and selected execution traces.
4. Treat Solana and Polkadot runtime execution as target-specific follow-up testing, not as the primary `solc` vs `solang` runtime oracle.

Solang's current upstream documentation emphasizes Solana and Polkadot targets. The local pinned binary confirms that those are the officially listed targets for this version. The existing Python harness can pass `--target evm`, but the trial below shows that this path is not currently suitable for runtime artifact generation.

## Local Trial Results

The following smoke trials were run without installing anything globally. Temporary files were placed under `/tmp/opencode/solidity-runtime-trial`, and runtime tools were invoked with `nix develop` or `nix-shell -p ...`.

### Toolchain Versions

Commands:

```bash
nix develop -c solc --version
nix develop -c solang --version
nix develop -c solang compile --help
```

Observed:

- `solc` is available in the project dev shell as `0.8.33+commit.64118f21`.
- `solang` is available in the project dev shell as `v0.3.4`.
- `solang compile --help` lists target values `solana` and `polkadot`, not `evm`.

### Smoke Contract

The trial used a small deterministic contract with constructor state, one mutating function, and one pure tuple-returning function:

```solidity
// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.20;

contract Smoke {
    uint256 public total;

    constructor(uint256 seed) {
        total = seed + 1;
    }

    function add(uint256 value) external returns (uint256) {
        total += value;
        return total;
    }

    function purePair(uint256 left, uint256 right)
        external
        pure
        returns (uint256, uint256)
    {
        return (right + 1, left + 2);
    }
}
```

### Compilation Outcomes

Commands:

```bash
nix develop -c solc --bin --abi --overwrite \
  -o /tmp/opencode/solidity-runtime-trial/solc-out \
  /tmp/opencode/solidity-runtime-trial/Smoke.sol

nix develop -c solang compile --target evm \
  --output /tmp/opencode/solidity-runtime-trial/solang-out \
  /tmp/opencode/solidity-runtime-trial/Smoke.sol

nix develop -c solang compile --target solana \
  --output /tmp/opencode/solidity-runtime-trial/solang-solana-out \
  /tmp/opencode/solidity-runtime-trial/Smoke.sol

nix develop -c solang compile --target polkadot \
  --output /tmp/opencode/solidity-runtime-trial/solang-polkadot-out \
  /tmp/opencode/solidity-runtime-trial/Smoke.sol
```

Observed:

- `solc` successfully emitted `Smoke.bin` and `Smoke.abi`.
- `solang --target evm` failed with a Rust panic: `not implemented: target not implemented`.
- `solang --target solana` successfully emitted `Smoke.so` and `Smoke.json`.
- `solang --target polkadot` successfully emitted `Smoke.wasm` and `Smoke.contract`.

This means the current repository can test Solang's documented non-EVM runtime targets, but cannot currently run a complete same-EVM-runtime comparison between `solc` and pinned Solang 0.3.4.

### Local EVM Runner Availability

Commands:

```bash
nix-shell -p go-ethereum --run "evm --help"
nix-shell -p foundry --run "anvil --version"
```

Observed:

- `go-ethereum` is available through `nix-shell -p go-ethereum` and provides `evm 1.17.3-stable`.
- `foundry` is available through `nix-shell -p foundry` and provides Anvil from the Foundry package.
- Both trials used Nix store paths only and did not require `nix-env` or global package installation.

### EVM Execution Smoke Check

Command:

```bash
nix-shell -p go-ethereum --run '
  bytecode=$(tr -d "\n" < /tmp/opencode/solidity-runtime-trial/solc-out/Smoke.bin)
  evm run --create "${bytecode}0000000000000000000000000000000000000000000000000000000000000005"
'
```

Observed:

- Geth's `evm run --create` executed the `solc` creation bytecode with an ABI-encoded constructor argument.
- The command returned deployed runtime bytecode.
- Running without constructor arguments reverted, which is expected for this constructor-bearing contract.

This validates `go-ethereum`'s `evm` command as a low-pollution local EVM execution candidate, but it does not validate full compiler differential runtime comparison because the pinned Solang did not produce EVM bytecode.

## Project Context

The repository currently performs compile-focused differential testing:

- `working/scripts/compare-compile.nu` compares `solc --abi --bin` with `solang compile --target solana` for deterministic seeds.
- `src/solidity_diff_fuzz/` defaults to `solang --target evm` and compares normalized compiler outcomes.
- The Python oracle treats crashes, acceptance mismatches, and diagnostic-class mismatches as interesting, while filtering unsupported-feature gaps.
- Existing planning notes already identify runtime behavior mismatch as a future extension for shared-success EVM seeds.

Runtime differential testing should not compare raw artifact bytes. `solc` and `solang` may differ in metadata layout, optimizer choices, auxiliary data, artifact names, and code shape while still implementing the same Solidity semantics. The oracle should compare externally observable behavior under controlled inputs.

## Runtime Requirements

A usable shared runtime environment should satisfy these requirements:

- Runs artifacts from both compilers without target translation.
- Provides deterministic execution with controlled block context, caller, value, gas limit, chain id, and account state.
- Exposes machine-readable observations: return bytes, revert bytes, emitted logs, storage state, call success/failure, and ideally execution traces.
- Supports contract deployment, ABI calls, constructor arguments, and repeated transactions.
- Is easy to script from the repository's Python harness or a small command-line wrapper.
- Can disable or normalize noisy differences such as metadata, gas accounting, source maps, and debug-only output.
- Has low setup cost under Nix and does not require remote chains or external services.

## Option 1: Shared EVM Runtime

### Description

Compile the same Solidity source with:

- `solc --bin --abi`, producing standard EVM bytecode.
- `solang compile --target evm`, producing Solang's EVM bytecode and ABI metadata.

Then deploy each contract into the same local EVM implementation and invoke the same ABI calls with the same calldata, sender, value, block context, and initial state. This requires an EVM-capable Solang build. The pinned Solang 0.3.4 binary in this repository did not satisfy that requirement in the local trial.

### Machine-Observable Outputs

The harness can compare:

- Deployment result: success, revert, invalid opcode, out-of-gas-like failure, or VM error.
- Runtime call result: success flag plus return bytes.
- Revert output: revert selector and encoded error data.
- Logs: topics and data.
- Storage snapshots after each transaction.
- Account balance and nonce changes if value transfer is tested.
- Optional instruction-level traces for debugging minimized cases.

### Candidate EVM Engines

Several local engines could serve this role:

- Foundry Anvil / Forge: strong Solidity/EVM developer ergonomics, scriptable local node, useful traces, and good support for JSON-RPC interaction.
- Geth `evm` tool: lightweight standalone EVM execution and tracing, good for bytecode-level execution, less convenient for full multi-call contract lifecycle tests.
- REVM-based custom runner: Rust library with deterministic in-process execution, excellent for a purpose-built oracle, but requires writing and maintaining a runner.
- EthereumJS VM: JavaScript VM with programmatic control, but would add a Node toolchain that this repository currently avoids.
- Hardhat Network: convenient but Node-heavy and less aligned with this repository's Nix/uv Python workflow.

Given the project constraints and the trial results, the fastest local prototype is Geth's `evm` tool through `nix-shell -p go-ethereum`; it can execute `solc` creation bytecode without adding anything to the global environment. Anvil is also available through `nix-shell -p foundry` and is a viable JSON-RPC candidate if the harness needs transaction sequencing, deployed contract state, and easier ABI-call orchestration. The cleanest long-term design remains either a small REVM runner exposed as a CLI or a minimal JSON-RPC harness against Anvil if Foundry is added to `flake.nix`.

### Strengths

- Same target architecture for both compilers.
- Best semantic alignment with `solc`, whose main output target is EVM.
- Low-noise comparison of ABI-visible behavior.
- Can reuse the existing shared-success seeds mentioned in `working/scripts/generate_seeds.py`.
- Does not need remote chains, validators, faucets, wallets, or asynchronous finality.
- Naturally supports deterministic differential testing by fixing VM environment fields.

### Weaknesses and Risks

- Solang EVM support in the pinned 0.3.4 binary is not usable for runtime artifact generation in the smoke trial; it panics with `not implemented: target not implemented`.
- Solang EVM output may have target gaps, so unsupported-feature filtering remains necessary.
- Gas differences are expected and should not be primary bugs unless the tested semantic is explicitly gas-sensitive.
- Constructors, immutables, libraries, external calls, and inheritance need careful harness handling.
- ABI metadata produced by Solang may differ from `solc`; the harness should prefer one canonical ABI source, usually `solc`, for call generation when both compilers accept the same source.

### Recommended EVM Oracle

The first runtime oracle should compare only deterministic ABI-level behavior:

1. Compile with both compilers.
2. If either compiler fails, leave the case to the existing compile oracle.
3. Extract a canonical ABI from `solc`.
4. Deploy both bytecodes in clean VM states with identical environment fields.
5. Invoke a bounded list of generated public/external functions with generated arguments.
6. Compare success flag and return bytes.
7. If calls mutate state, compare selected getter return values or full storage snapshots after each call.

The initial case set should avoid:

- `block.*`, `tx.*`, `msg.value`, `gasleft()`, `basefee`, randomness-like environment reads, and timestamp dependence unless explicitly controlled.
- Unbounded loops, gas-boundary behavior, and tests whose only difference is gas consumption.
- External contract dependencies, `delegatecall`, `create2`, selfdestruct, payable transfer side effects, and precompile behavior.
- Inline assembly until the high-level Solidity oracle is stable.

## Option 2: Solana Runtime / SBF BPF Loader

### Description

Compile with `solang --target solana` and run the resulting SBF program under a local Solana test validator, `solana-program-test`, or a lower-level SBF VM. This is a natural runtime target for Solang, but `solc` does not emit Solana programs.

### Machine-Observable Outputs

The harness could compare:

- Transaction success or failure.
- Anchor IDL-visible return or account effects where applicable.
- Program logs.
- Account data changes.
- Compute unit usage if needed for debugging, but not as a primary semantic oracle.

### Strengths

- Solang's Solana target is a documented primary target.
- Local validator/program-test workflows can produce deterministic account-state observations.
- Useful for Solang-specific backend fuzzing and regression testing.

### Weaknesses

- There is no direct `solc` output for Solana, so it cannot provide same-runtime `solc` vs `solang` execution.
- Any comparison against `solc` would require a semantic adapter, reimplementation, interpreter, or source-level expected-output oracle.
- Solana account semantics differ substantially from EVM storage, value transfer, and call semantics.
- Harness complexity is higher: account setup, signers, rent, instruction data, and transaction lifecycle must be controlled.

### Assessment

Solana is not a primary answer to the `same output for solang and solc` requirement. It is valuable as a second line of testing for Solang's own target behavior after an EVM shared-success case has identified a source-level area worth probing.

## Option 3: Polkadot/Substrate Contracts Runtime

### Description

Compile with `solang --target polkadot` and run the resulting Wasm contract under a local Substrate contracts pallet environment or `pallet-contracts` sandbox tooling.

### Machine-Observable Outputs

The harness could compare:

- Instantiation success or failure.
- Contract call success and returned bytes.
- Events.
- Contract storage changes.
- Trap or revert information.

### Strengths

- Documented Solang target.
- Wasm execution can be deterministic and machine-observable.
- Useful for target-specific Solang backend testing.

### Weaknesses

- `solc` does not emit Substrate-compatible Wasm contracts.
- Contract host semantics differ from EVM semantics.
- Requires Substrate-specific tooling and runtime setup.
- Differential comparison would mostly be against manually generated expectations, not against `solc` artifacts.

### Assessment

Polkadot/Substrate is unsuitable as the primary `solc` vs `solang` runtime environment. It can be a later Solang backend test target, but not a shared runtime oracle.

## Option 4: Source-Level Reference Oracle Instead of Shared Runtime

### Description

Generate Solidity programs whose expected outputs are known by construction, then compile and run each compiler's artifact in its native target runtime. For example, a generator could produce a function `check()` that must return a fixed tuple or emit a fixed digest.

### Machine-Observable Outputs

The harness compares each runtime result to a generated expected value rather than directly comparing two artifacts in the same VM.

### Strengths

- Can support non-EVM Solang targets.
- Avoids needing `solc` to target Solana or Polkadot.
- Good for simple arithmetic, ABI, storage, and control-flow properties.

### Weaknesses

- Much harder to generate correct expected values for complex Solidity semantics.
- Bugs in the generator/oracle can produce false positives.
- Cross-target semantic differences must be abstracted carefully.
- Less powerful than direct differential testing because the expected-output oracle narrows the program space.

### Assessment

This is a useful complement, not a replacement. It is best for a curated set of small tests and for extending beyond EVM after the direct EVM oracle is working.

## Option 5: Trace or IR Comparison

### Description

Instead of comparing final return values only, inspect intermediate traces, compiler IR, or VM instruction traces.

### Possible Observations

- EVM opcode traces.
- Stack/memory/storage deltas.
- LLVM IR from Solang via `--emit llvm-ir`.
- Yul or EVM assembly from `solc`.

### Strengths

- Useful for reducing and diagnosing mismatches.
- Can reveal divergence before a final return value differs.
- Helps classify whether a mismatch is frontend, lowering, optimizer, or backend related.

### Weaknesses

- Not a stable primary oracle because different compilers are allowed to produce different intermediate code.
- Trace alignment between different bytecodes is hard.
- More likely to flag benign implementation differences.

### Assessment

Trace comparison should be a diagnostic aid after ABI-level mismatch detection, not the main oracle.

## Recommendation Matrix

| Option | Same runtime for both compilers | Machine-observable | Setup cost | Signal-to-noise | Recommended role |
| --- | --- | --- | --- | --- | --- |
| Shared EVM runtime | Yes | High | Medium | High | Primary runtime oracle |
| Solana runtime | No | High | High | Medium | Solang target follow-up |
| Polkadot/Substrate runtime | No | High | High | Medium | Solang target follow-up |
| Source-level expected oracle | Partially | Medium | Medium | Medium | Complementary curated tests |
| Trace/IR comparison | Partially | High | Medium | Low as oracle, high for debugging | Diagnostic aid |

## Proposed Harness Architecture

The runtime harness should be added as a separate phase after compilation:

```text
Solidity source
  -> compile with solc
  -> compile with solang --target evm
  -> if both succeed, deploy both bytecodes into identical local EVM states
  -> run generated ABI calls
  -> normalize observations
  -> classify runtime mismatch
```

Suggested Python-side data model:

- `RuntimeInput`: contract name, ABI, constructor args, function calls, callers, values, environment fields.
- `RuntimeObservation`: deploy status, per-call status, return data, revert data, logs, storage snapshot, VM error.
- `RuntimeMismatch`: source path, compiler pair, call index, normalized observation pair, signature.

Suggested mismatch classes:

- `runtime.deploy.status`: one deployment succeeds and the other fails.
- `runtime.call.status`: one call succeeds and the other reverts or traps.
- `runtime.call.return`: both calls succeed but return bytes differ.
- `runtime.call.revert`: both revert but revert bytes or error classes differ.
- `runtime.logs`: event topics/data differ.
- `runtime.storage`: post-call storage differs after a state-mutating sequence.
- `runtime.vm-error`: one runtime hits an engine-level error.

## Minimum Viable Runtime Experiment

The smallest useful experiment should use only one contract at a time and deterministic public functions.

Candidate seeds from the existing generator comments and planning notes:

- Tuple swap with pure/view getter.
- Compound assignment over fixed integer widths.
- Constructor state flow with a getter.
- Struct roundtrip returning ABI-encodable fields.
- Fixed-array assignment returning selected elements.
- Modifier ordering with explicit state counter.
- Bytes/hash roundtrip using deterministic input bytes.

Initial comparison policy:

- Use `solc` ABI as canonical ABI.
- Use one fixed caller address, zero value, fixed chain id, fixed block number, fixed timestamp, fixed gas limit.
- Ignore gas used unless the case is specifically about gas-sensitive behavior.
- Compare exact ABI return bytes for successful calls.
- For state-mutating calls, follow with generated view/getter calls and compare their return bytes before attempting raw storage comparison.

## Tooling Recommendation

Short term:

- Prototype with whichever local EVM runner is easiest to add to `flake.nix` and invoke from Python.
- Prefer command-line or JSON-RPC interfaces that can be wrapped without introducing a large framework.
- Keep runtime tests opt-in so compile fuzzing remains fast.

Medium term:

- Add a purpose-built in-process EVM runner if command-line tooling becomes hard to normalize.
- Store runtime observations as JSON under `artifacts/` next to the existing compile records.
- Add minimization support that preserves the specific runtime mismatch signature.

Long term:

- Add Solana and Polkadot runners only for Solang-specific backend campaigns.
- Add source-level expected-output tests for cases that should project across EVM, Solana, and Polkadot.

## Risks and Mitigations

| Risk | Mitigation |
| --- | --- |
| Solang EVM target behavior changes or disappears in future releases | Pin Solang versions in Nix and record compiler versions in every run artifact. |
| ABI metadata differs across compilers | Use a canonical ABI from `solc` for call generation and separately record Solang ABI for debugging. |
| Runtime mismatches caused by unsupported features | Keep existing unsupported-feature filters and add runtime eligibility tags to generated cases. |
| False positives from environmental values | Fix block, transaction, and account context; avoid environment-dependent seeds initially. |
| False positives from gas differences | Do not compare gas by default; classify out-of-gas separately only under controlled gas budgets. |
| Harness bugs | Start with hand-audited deterministic seeds and cross-check with known expected return values. |
| Toolchain bloat | Add runtime tools through `flake.nix`; avoid Node-heavy workflows unless no lighter option works. |

## Final Recommendation

Use EVM as the primary shared-runtime design target for `solc` vs `solang` differential testing. It is the only realistic path that gives both compilers a common execution target and produces stable machine-observable outputs.

However, do not start by wiring a full EVM runtime oracle against the currently pinned Solang 0.3.4 binary. The local trial shows that this binary emits Solana and Polkadot artifacts, but not EVM runtime artifacts. The next engineering decision should be whether to pin/build a Solang version with working EVM output, or whether to keep the current compiler oracle and add runtime testing only for Solang's Solana/Polkadot targets plus `solc`-only EVM smoke checks.

The first implementation should be intentionally narrow: compile shared-success contracts, deploy both bytecodes into identical local EVM states, execute generated ABI calls, and compare success flags plus return bytes. Once this is reliable, extend the oracle to revert data, logs, state snapshots, and trace capture for debugging.

Solana and Polkadot should remain secondary Solang-target campaigns. They are useful for finding backend bugs in Solang, but they do not satisfy the core requirement of running both `solc` and `solang` outputs in the same runtime.
