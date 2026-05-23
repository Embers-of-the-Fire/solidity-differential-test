# Potential Solutions for Solang Transaction Testing

## Goal

We want to test Solang transaction behavior, not only pure function execution. The key question is how to run Solang-compiled contracts in an environment that is realistic enough to expose transaction bugs, while still being practical for fuzzing and repeated experiments.

The main conclusion is that we should not try to simulate an entire blockchain first. A layered approach is more practical: use a fast local mock runtime for broad testing, then replay interesting cases on a real local chain.

## Solution 1: Extend the Current Wasm Runner

The current harness already executes Solang Polkadot Wasm with minimal host stubs. We can extend it into a lightweight transaction simulator.

This would add a small local model for:

- accounts
- contract instances
- caller context
- value transfer
- persistent storage
- multi-step transactions
- transaction result capture

This solution is the easiest to integrate into the current Python fuzzer. It would be fast, deterministic, and suitable for generating many test cases.

The downside is accuracy. Every contracts-pallet host function we emulate becomes part of our trusted model. If the model is incomplete, it can produce false positives or miss real bugs.

Recommended use: first-stage fuzzing and quick bug discovery.

## Solution 2: Reuse Solang's Own Mock VM Ideas

Solang's test documentation mentions a mock contract virtual machine for Polkadot and Solana. For Polkadot, it uses a Wasm VM and implements runtime calls closely enough for compiler tests.

This gives us a strong design reference. Instead of inventing every behavior from scratch, we can inspect Solang's mock VM and copy the same basic structure into this repository, or build a small adapter around similar assumptions.

The likely shape is:

- compile Solidity with Solang
- load the generated Wasm
- provide contracts-pallet-like host functions
- keep mock chain state in memory
- execute deploy and call steps
- record normalized observations

This is still a mock environment, but it has precedent in Solang's own testing strategy.

Recommended use: guide the design of our local transaction simulator.

## Solution 3: Use `aqd` Against a Local Contracts-Pallet Chain

Solang provides `aqd`, a command-line tool for deploying and calling Solang contracts on Polkadot and Solana targets. For Polkadot, it uses existing contracts tooling underneath.

This is not currently available in the repository's Nix dev shell, so the first implementation should not depend on it until the tool is added to the flake or replaced with another verified local-chain interface.

This is much closer to real transaction behavior than a Python mock. It can validate deployment, instantiation, calls, reverts, storage effects, balances, and events through the actual contracts pallet.

The downside is speed and operational complexity. It requires a local compatible chain or endpoint, startup management, account setup, and parsing chain responses.

Recommended use: confirmation backend for cases found by the fast mock runner.

## Solution 4: Use `cargo-contract` Directly

For Polkadot contracts, `cargo-contract` is a standard tool for uploading, instantiating, calling, and dry-running contracts.

Using it directly may expose more configuration and diagnostics than `aqd`, especially around gas limits, storage deposit limits, dry runs, and metadata handling.

The tradeoff is that `cargo-contract` is not Solang-specific, and it is not currently available in the repository's Nix dev shell. We would need to add it through the Nix environment before treating this as an executable backend.

Recommended use: alternative real-chain backend if `aqd` is too limited.

## Solution 5: Use Chopsticks for Forked Chain Testing

Chopsticks can fork Polkadot SDK chains locally, manipulate storage, replay blocks, and control block production. It is useful when the test needs realistic chain state but should not run against a live network.

This is more powerful than a simple dev chain, but likely too heavy for the first implementation. It also targets native Polkadot SDK APIs rather than Ethereum JSON-RPC. It is not currently available in the repository's Nix dev shell, so it should remain a later investigation item rather than part of the initial executable plan.

Recommended use: later-stage replay and debugging, especially for bugs that depend on chain state, block timing, or storage setup.

## Recommended Path

The best path is a two-backend design.

First backend: local mock transaction runner.

- Fast enough for fuzzing.
- Easy to integrate with the current Python harness.
- Deterministic and cheap to run.
- Good for generating candidate bugs.

Second backend: real local contracts-pallet runner.

- Uses a verified local-chain interface after it has been added to the Nix environment.
- Slower but more faithful.
- Confirms whether mock-discovered candidates reproduce under actual transaction semantics.

The shared input should be a small scenario file, independent of backend implementation. The following is a proposed format sketch, not an executable command:

```yaml
accounts:
  alice:
    balance: 1000000000000

steps:
  - instantiate:
      from: alice
      constructor: new
      args: [0]

  - tx:
      from: alice
      message: increment
      args: [3]

  - query:
      from: alice
      message: get
      args: []
      expect:
        returns: [3]
```

This keeps the harness flexible. The same scenario can run first in the mock backend, then be replayed on the local-chain backend if it looks interesting.

## Implementation Order

1. Define the scenario format and result schema.
2. Add a mock Polkadot transaction runner by extending the current Wasm host-stub runner.
3. Support one simple stateful contract family: constructor, storage write, storage read.
4. Add revert handling and event capture.
5. Add a replay backend using a verified local contracts-pallet interface.
6. Use Chopsticks only if local-chain replay is not enough.

## Final Recommendation

Start with the mock runner, but design it as a candidate generator only. Do not treat mock-only failures as final bugs.

The practical research workflow should be:

```text
generate scenario -> run mock backend -> find candidate -> replay on local chain -> minimize -> report
```

This avoids the cost of full-chain testing for every fuzz case while still giving a credible path to transaction-level bug confirmation.
