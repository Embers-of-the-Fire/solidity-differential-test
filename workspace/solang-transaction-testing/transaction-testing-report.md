# Weekly Report: Observable Runtime Differential Testing

## Goal

This week focuses on the runtime part of `solc` vs Solang differential testing.

The target comparison is:

```text
solc -> EVM execution
vs
Solang -> Polkadot Wasm/contracts-pallet execution
```

The comparison should use observable behavior, not raw bytecode or raw ABI bytes.

## Current Method

Run the same logical Solidity scenario on both platforms:

1. Compile the contract with `solc` for EVM.
2. Compile the contract with `solang --target polkadot` for Wasm and `.contract` metadata.
3. Execute the EVM artifact in a deterministic EVM runner.
4. Execute the Solang artifact in a Polkadot runtime path.
5. Decode both outputs into a shared observation format.
6. Compare decoded observations step by step.

The comparison fields are:

- success or revert
- decoded return values
- decoded revert kind and message when available
- event presence and decoded event fields
- storage state observed through later queries
- caller and transferred-value behavior

Gas, weight, raw byte layout, and backend-specific address format are recorded for debugging but are not compared by default.

## Minimal Example

The first scenario is a small counter contract:

```solidity
// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.20;

contract Counter {
    uint256 private total;

    event Incremented(address indexed caller, uint256 delta, uint256 value);

    constructor(uint256 initial) payable {
        total = initial;
    }

    function get() external view returns (uint256) {
        return total;
    }

    function increment(uint256 delta) external payable {
        require(delta > 0, "zero increment");
        total += delta;
        emit Incremented(msg.sender, delta, msg.value);
    }
}
```

Scenario:

```text
deploy Counter(5) from alice with value 10
query get() -> 5
tx increment(3) from bob with value 7
query get() -> 8
tx increment(0) -> revert
```

## Executable Commands

Compile EVM artifact:

```bash
nix develop -c solc --bin --abi --overwrite -o evm-out Counter.sol
```

Compile Solang Polkadot artifact:

```bash
nix develop -c solang compile --target polkadot --output polkadot-out Counter.sol
```

Run the current local Solang Polkadot transaction smoke:

```bash
nix develop -c uv run solidity-diff-fuzz transaction-smoke \
  workspace/solang-transaction-testing/contracts/StatefulCounter.sol \
  --work-dir /tmp/solang-transaction-smoke
```

Check the real contracts-pallet node:

```bash
nix develop -c substrate-contracts-node --version
```

Start the real contracts-pallet node:

```bash
nix develop -c substrate-contracts-node --dev --tmp --rpc-port 9944 --rpc-cors all
```

## Observation Format

The intended normalized output is:

```yaml
case: Counter.sol
status: equivalent-observations
steps:
  - step: 1
    kind: query
    message: get
    evm: {status: success, returns: [5]}
    polkadot: {status: success, returns: [5]}
  - step: 2
    kind: tx
    message: increment
    evm: {status: success, events: [Incremented]}
    polkadot: {status: success, events: [Incremented]}
  - step: 3
    kind: query
    message: get
    evm: {status: success, returns: [8]}
    polkadot: {status: success, returns: [8]}
  - step: 4
    kind: tx
    message: increment
    evm: {status: revert, error: Error(string)}
    polkadot: {status: revert, error: Error(string)}
```

If a decoded field differs, the case becomes a runtime mismatch. If the local Wasm host reports a mismatch, the Solang side should be replayed on the real contracts-pallet node before treating it as confirmed.

## Current Status

Completed this week:

- Confirmed `solc` can produce EVM artifacts.
- Confirmed Solang can produce Polkadot `.wasm` and `.contract` artifacts.
- Confirmed the pinned Solang EVM target is not usable.
- Built and ran a local Solang Polkadot Wasm transaction smoke path.
- Verified the real `substrate-contracts-node` binary is available.

Current gap:

- The real contracts-pallet node can start, but automated upload, instantiate, query, and transaction replay is not implemented yet.

## Next Work

Next week should focus on the real-node runner:

```text
compile .contract
start substrate-contracts-node
upload contract
instantiate constructor
run query and tx steps
decode observations
compare against EVM observations
```

The preferred implementation path is to try `cargo-contract` first. If that is difficult to package or parse, use a small Polkadot.js `@polkadot/api-contract` runner that emits JSON observations.
