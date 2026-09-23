You are given an existing differential-testing probe (a JSON spec) that runs
the SAME Solidity source through two toolchains:

- EVM side: solc, executed on anvil (standard EVM semantics)
- Polkadot side: solang --target polkadot (WASM), executed on substrate-contracts-node (pallet-contracts)

Your job: produce $n MUTANTS of this probe. A mutant is a full, standalone
spec derived from the parent by applying a SMALL number of source-level or
sequence-level mutations. Mutants should stay close to the parent (they
inherit its hypotheses) but explore its neighborhood — you are looking for
nearby inputs where the two toolchains diverge.

# Parent spec

```json
$parent_spec_json
```

# Parent outcome

$parent_outcome

# Target area (seed card)

$id: $title
$why

Hints:
$hints

# Current hypotheses for this area

$hypotheses

# Mutation menu (apply 1-3 per mutant; vary the choice across mutants)

- literal -> boundary value: replace an integer literal with 2**k-1, 2**k,
  2**k+1, 0, 1, or a sign edge (-1, -2**(k-1)) matching its width
- integer width/sign change: uint8 <-> uint16 <-> uint256 <-> int8 ... int256
- operator substitution: + <-> -, * <-> /, << <-> >>, < <-> <=, == <-> !=
- storage layout perturbation: reorder fields, or add a small field, to
  change slot packing
- wrap/unwrap a statement in `unchecked { }`
- delete or duplicate a statement; swap two statements
- add a second function interacting with the same state variable
- sequence-level: reorder/duplicate steps, change a sender, change an arg
  to a boundary value

# Output contract

Reply with ONE JSON object and nothing else:

{"mutants": [<spec>, <spec>, ...]}

- Exactly $n specs, each a COMPLETE spec (same schema as the parent).
- Give each mutant a distinct "name" derived from the parent's name.
- Each mutant must differ from the parent in at least one mutation.

# Hard constraints (violations are discarded, wasting the mutant)

- Exactly ONE contract per spec. Inline source only (no imports).
- "action" is "call" (state-changing) or "query" (read-only).
- Steps are dispatched by FUNCTION NAME + JSON args only. No raw calldata.
- Senders: only "deployer", "alice", "bob", "charlie".
- Addresses in args: use "$$deployer", "$$alice", "$$bob", "$$charlie", "$$contract".
- Args must be JSON scalars, hex strings for bytesN/bytes ("0x..."), or arrays.
  NO structs/tuples as args.
- value: integer, keep it small (<= 10**15).
- Max 8 steps. Keep contracts small (< 60 lines). Every step's function must
  exist in the contract.
- Solidity pragma: use "pragma solidity >=0.8.0;".
- Both compilers must accept the source UNLESS the asymmetry itself is the probe.

Reply with ONLY the JSON object.
