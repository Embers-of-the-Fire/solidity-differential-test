# Review finding-50a81738730ee902

Status: **survivor**; origin: `finding`

## Minimized/current spec

```solidity
pragma solidity >=0.8.0;

contract Int8DivProvenance {
    uint256 public count;
    int8 public a = type(int8).min;
    int8 public b = -1;
    int8 public last;

    function divStored() external returns (int8) {
        int8 r = a / b;
        last = r;
        count += 1;
        return r;
    }

    
}
```

## Earliest divergence

```json
{
  "point": 0,
  "signature": "STATUS_MISMATCH|0|divStored|revert\u2260success"
}
```

## Panel

```json
[
  {
    "category": "bug_candidate",
    "confidence": "high",
    "evidence": "Source: a = type(int8).min (-128), b = -1; call divStored performs a / b. EVM reverts (dry-run and committed status 'revert'), consistent with Solidity 0.8 checked arithmetic where INT_MIN / -1 = 128 overflows int8 and panics (Panic 0x11). Polkadot reports success; committed storage shows last = -128 and count = 1, i.e. solang silently wrapped the result to -128 (0x80) instead of reverting.",
    "rationale": "In Solidity >=0.8, signed division of the minimum value by -1 is a checked operation that must revert with a panic, since the mathematical result (+128) is not representable in int8. The solang run returned success with last = -128, indicating missing overflow detection on signed division (or constant-folded signed division) in solang's Polkadot codegen. The divergence is deterministic, semantic, and not explained by environment values, gas, or oracle projection: the storage-count mode merely reflects that EVM state was rolled back while Polkadot state committed.",
    "historical_match_url": "",
    "cluster_hint": "solang missing overflow revert for signed division INT_MIN / -1 (int8), wrapping instead of panicking"
  },
  {
    "category": "bug_candidate",
    "confidence": "high",
    "evidence": "EVM dry-run and committed tx revert for divStored() with a = type(int8).min (-128), b = -1; solang/Polkadot returns success and stores last=-128, count=1. Per Solidity 0.8 checked arithmetic semantics, INT8_MIN / -1 overflows int8 range and must panic (revert), which solc does. Solang produced the wrapped result -128 without reverting.",
    "rationale": "Solidity >=0.8.0 requires overflow-checked division, and -128 / -1 = +128 is not representable in int8, so the correct behavior is a reverting panic. The EVM oracle reverts as expected, while solang silently wraps to -128 and increments count. This is a semantic defect in solang's signed division codegen for narrow integer types, not an environment, oracle-projection, or gas artifact.",
    "historical_match_url": "",
    "cluster_hint": "solang missing signed-division overflow check for narrow signed ints (int8 min / -1 wraps instead of panicking)"
  }
]
```

## Adversarial review

```json
{
  "rebuttal_succeeds": false,
  "category": "bug_candidate",
  "evidence": "The contract performs a/b with a = type(int8).min (-128) and b = -1 under pragma >=0.8.0. Solidity 0.8 checked arithmetic mandates a revert (Panic 0x11) because +128 is unrepresentable in int8; the EVM oracle reverts in both dry-run and committed transaction. Solang/Polkadot instead returns success and commits last = -128 (0x80, the exact two's-complement wrap of +128) with count = 1. The stored value being precisely the wrapped result, rather than garbage or an environment-dependent value, indicates the division executed without an overflow check. The divergence involves none of the documented known-difference markers (no block/tx environment reads, gas comparison disabled, oracle storage projection only reflects the revert-vs-success split rather than causing it). None of the supplied historical records describe this behavior, so rediscovery cannot be established from the given evidence.",
  "rationale": "This is a deterministic semantic divergence on a core language operation: solang fails to implement the Solidity 0.8 checked-arithmetic revert for signed division INT_MIN / -1 on int8, silently wrapping instead. It is not explained by platform environment values, gas models, or oracle artifacts, and no supplied historical record documents it as intended behavior or a known prior report. The evidence survives adversarial scrutiny.",
  "historical_match_url": ""
}
```

## Potentially relevant historical records

- Inconsistent behaviour when calling function via contract type name: https://github.com/hyperledger-solang/solang/issues/1007
- Add Rename functionality: https://github.com/hyperledger-solang/solang/pull/1514
- v0.3.3: Atlantis: https://github.com/hyperledger-solang/solang/pull/1573
- [Snyk] Upgrade @solana/spl-token from 0.3.8 to 0.3.9: https://github.com/hyperledger-solang/solang/pull/1607
- CHANGELOG v0.3.4: 
- Thread 'main' panicked  error when compiling call with seeds: https://github.com/hyperledger-solang/solang/issues/1028
- thread 'main' panicked while compiling BlindAuction from Solidity official website: https://github.com/hyperledger-solang/solang/issues/1076
- llvm-dis fails to disassemble bitcode file generated by Solang for a smart contract: https://github.com/hyperledger-solang/solang/issues/641

Human semantic review and a current open+closed upstream search are required before counting this as a new bug.
