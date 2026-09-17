You are minimizing a differential-testing reproducer. The Solidity contract below
produces a behavioral divergence between solc (EVM) and solang (Polkadot WASM).
Make the contract AS SMALL AS POSSIBLE while preserving the divergence.

# Rules

- The divergence involves these function(s): $functions — keep them callable
  with the same signatures and the same observable behavior.
- Remove unrelated state variables, functions, events and code paths.
- Simplify expressions only when the divergent behavior is preserved.
- Keep "pragma solidity >=0.8.0;" and a single contract named "$contract".
- Do NOT use structs/tuples in public function signatures.

# Divergence evidence

$divergences_json

# Current contract

```solidity
$source
```

Reply with ONLY one JSON object: {"solidity": "<minimized complete source>"}.
