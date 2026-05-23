# Solang Transaction Runtime Notes

This folder documents two paths for inspecting Solang Polkadot transaction behavior:

- a local in-memory runtime for fast inspection
- a real local contracts-pallet node for trusted chain execution

The real node is `substrate-contracts-node` from Parity's public release `v0.42.0`, packaged through `flake.nix` with the upstream published tarball checksum.

The core discovery is that Solang Polkadot contracts are Wasm modules with two relevant exports:

- `deploy`: constructor/instantiation entrypoint.
- `call`: message/call entrypoint.

The module does not run by itself. It expects contracts-pallet-style host functions under `seal0`, `seal1`, and `seal2`. Runtime behavior becomes inspectable when the harness provides those host functions and records what the contract does through them.

## Runtime Model

The local runtime is a small in-memory model, not a complete blockchain.

It provides enough host behavior to inspect stateful transaction semantics:

- input calldata is passed through `seal0.input`
- transferred value is passed through `seal0.value_transferred`
- caller identity is passed through `seal0.caller`
- contract storage is read through `seal1.get_storage`
- contract storage is written through `seal2.set_storage`
- emitted events are captured through `seal0.deposit_event`
- success or revert data is captured through `seal0.seal_return`

Storage is a Python dictionary keyed by raw storage keys. Calls share the same dictionary, so state persists across deploy, transaction, and query steps.

This lets the harness inspect whether a contract deployment writes state, whether later calls read that state, whether transactions mutate it, and whether a revert is reported through returned error data.

## Interpretation Rules

The local runtime observes behavior, not full chain consensus.

Use these rules when interpreting results:

- A transaction is considered successful when `seal_return` does not set the revert flag.
- A reverted call is still a valid runtime observation, not a harness crash.
- Query return values are decoded from Solang Polkadot's little-endian `uint256` representation.
- Transaction return bytes are less important than durable effects: storage, events, success/revert status, and later query results.
- Event data is captured as raw topics and data. It is inspectable even when not fully decoded.
- Caller and transferred value are controlled by the harness, so tests can distinguish account-sensitive behavior.

The local runtime is useful as a bug-finding and inspection layer. It should not be treated as a complete substitute for the real contracts-pallet node.

## Verified Behavior

`contracts/StatefulCounter.sol` exercises the minimal transaction model:

- constructor stores an initial value
- `get()` reads stored value
- `increment(uint256)` mutates storage
- `increment(uint256)` records caller and transferred value
- `increment(uint256)` emits an event
- `increment(0)` reverts with `Error(string)` data

The verified runtime sequence is:

1. Deploy `StatefulCounter` with initial value `5` and value `10` from Alice.
2. Query `get()` and observe decoded value `5`.
3. Send transaction `increment(3)` from Bob with value `7`.
4. Observe an emitted event.
5. Query `get()` and observe decoded value `8`.
6. Send transaction `increment(0)` and observe a revert.

This proves that runtime behavior is currently runnable and inspectable for constructor state, persistent storage, caller/value context, event capture, query return values, and revert data in the local inspection backend.

## Real-Chain Baseline

The Nix dev shell now includes a real contracts-pallet development node:

- package: `substrate-contracts-node`
- version: `0.42.0-f209befc88c`
- upstream release: `paritytech/substrate-contracts-node v0.42.0`
- upstream checksum for `substrate-contracts-node-linux.tar.gz`: `a631b4e83dd05e4beaccbd770be709ac41914183d443116c2e4d244161590265`

This node provides the publicly trusted environment for real-chain replay. It can be started from the dev shell and exposes a local JSON-RPC endpoint for contracts-pallet transactions.

The node-level baseline is verified. Deployment/call automation still needs a client layer, such as `cargo-contract`, `aqd`, or a Substrate RPC script. Those clients are not available in the pinned `nixpkgs` by name, so the next step is to package or implement that client layer reproducibly.

## Fixture Layout

- `contracts/StatefulCounter.sol`: executable stateful fixture for the current runtime model.
- `contracts/CallerProxy.sol`: contract-to-contract fixture for future expansion.
- `scenarios/mock-stateful-counter.yaml`: scenario form of the verified stateful flow.
- `scenarios/mock-contract-call.yaml`: proposed scenario for contract-to-contract calls.
- `scenarios/local-chain-replay.yaml`: replay shape for the real contracts-pallet node backend.
- `scenarios/chopsticks-replay.yaml`: replay shape for a future forked-chain backend.
- `expected/*.normalized.yaml`: expected normalized observations for scenario execution.
- `checks/tool-availability.yaml`: current availability and runtime-check status.

## Current Boundary

The local runtime deliberately avoids full blockchain behavior.

It does not yet model:

- block production
- gas or weight charging
- storage deposits
- account balances as a global ledger
- contract instantiation from inside another contract
- complete event decoding
- full contracts-pallet error handling

The intended workflow is to use this local runtime to generate and inspect candidates, then replay interesting cases on the real local contracts-pallet node through a reproducible client layer.

## Tooling Status

Available in the current Nix dev shell:

- `solang`
- `wasm-tools`
- `substrate-contracts-node`
- repository CLI command `transaction-smoke`

Not currently available in the Nix dev shell:

- `aqd`
- `cargo-contract`
- `chopsticks`

Because `cargo-contract` and `aqd` are missing, real-chain node startup is available but contract deployment/call automation is still blocked on a reproducible client.

## Reproducing The Runtime Inspection

The main point of this folder is the runtime model above. For verification, the current executable check is:

```bash
nix develop -c uv run solidity-diff-fuzz transaction-smoke workspace/solang-transaction-testing/contracts/StatefulCounter.sol --work-dir /tmp/opencode/transaction-smoke-run
```

The expected high-level result is `Transaction smoke: pass` with observed deploy, query, transaction, event, query, and revert steps.

The real contracts-pallet node availability check is:

```bash
nix develop -c substrate-contracts-node --version
```

The expected high-level result is `substrate-contracts-node 0.42.0-f209befc88c`.

The real node starts with:

```bash
nix develop -c substrate-contracts-node --dev --tmp --rpc-port 9944 --rpc-cors all
```

That command runs a long-lived local chain process and exposes RPC on `127.0.0.1:9944`.
