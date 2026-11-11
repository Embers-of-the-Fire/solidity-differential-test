# Review finding-2fef5a0a1ecff327

Status: **survivor**; origin: `finding`

## Minimized/current spec

```solidity
pragma solidity >=0.8.0;

contract IntDivRuntimeArgs8 {
    uint8 public tag;
    int8 public last;
    uint256 public count;

    function tagSet(uint8 t) external {
        tag = t;
        count += 1;
    }

    function okDiv8() external returns (int8) {
        int8 x = type(int8).min / int8(2);
        count += 1;
        return x;
    }

    function divArgs8(int8 a, int8 b) external returns (int8) {
        int8 x = a / b;
        last = x;
        count += 1;
        return x;
    }
}
```

## Earliest divergence

```json
{
  "point": 2,
  "signature": "STATUS_MISMATCH|2|divArgs8|revert\u2260success"
}
```

## Panel

```json
[
  {
    "category": "bug_candidate",
    "confidence": "high",
    "evidence": "divArgs8(-128, -1) on int8: EVM dry-run and committed status = revert (Panic 0x11 arithmetic overflow, since -128 / -1 = 128 overflows int8), count stays at 2 on EVM. Polkadot status = success, last stored = -128 (silent wraparound), count incremented to 3.",
    "rationale": "Solidity 0.8 semantics require an overflow panic for type(int8).min / -1 because the mathematical result 128 is not representable in int8. solc correctly reverts; solang silently wraps to -128 and commits state, indicating missing signed-division overflow checking in solang codegen. The storage divergence (count 2 vs 3, last=-128) is fully explained by this single semantic defect, not by packing/endianness artifacts in count mode.",
    "historical_match_url": "",
    "cluster_hint": "solang does not trap signed division overflow: intN INT_MIN / -1 wraps instead of reverting with Panic(0x11)"
  },
  {
    "category": "bug_candidate",
    "confidence": "high",
    "evidence": "Step 2 calls divArgs8(-128,-1). EVM status=revert and storage count remains at non-zero value 2. Polkadot status=success with last=-128 and count=3, consistent with int8(-128) / int8(-1) wrapping to -128 instead of reverting.",
    "rationale": "Solidity 0.8 checked arithmetic makes signed division overflow for type(int8).min / -1 revert on EVM. Solang/Polkadot instead committed success and stored the wrapped two's-complement result -128 while incrementing count, indicating a missing SDIV overflow check for narrow signed ints rather than an environment, gas, revert-wording, or storage-count projection artifact.",
    "historical_match_url": "",
    "cluster_hint": "Polkadot codegen misses signed division overflow check for int8 min/-1, wrapping to -128"
  }
]
```

## Adversarial review

```json
{
  "rebuttal_succeeds": false,
  "category": "bug_candidate",
  "evidence": "At step 2, divArgs8(-128, -1) calculates type(int8).min / int8(-1). The mathematical result is 128, which is not representable in int8. EVM both dry-run and committed execution revert, while Polkadot commits success, stores last=-128, and increments count from 2 to 3.",
  "rationale": "Under checked Solidity 0.8 arithmetic, this operation must trigger an arithmetic overflow panic rather than wrap. The observed -128 result is exactly the two's-complement wraparound of 128, and the count/last storage differences directly follow from Polkadot committing where EVM reverts. This is not covered by the documented environment or gas-model differences, and none of the supplied historical records describe signed-division overflow behavior.",
  "historical_match_url": ""
}
```

## Potentially relevant historical records

- Inconsistent behaviour when calling function via contract type name: https://github.com/hyperledger-solang/solang/issues/1007
- Thread 'main' panicked  error when compiling call with seeds: https://github.com/hyperledger-solang/solang/issues/1028
- Solang should not ask functions that contain `address.call` to be declared as view: https://github.com/hyperledger-solang/solang/issues/997
- functions that use .call() should be not allowed in view functions: https://github.com/hyperledger-solang/solang/pull/1338
- Substrate: Implement builtin for `set_code_hash` API: https://github.com/hyperledger-solang/solang/pull/1397
- Add Rename functionality: https://github.com/hyperledger-solang/solang/pull/1514
- Allow seeds to be passed into functions as string[] or string[][]: https://github.com/hyperledger-solang/solang/pull/1547
- v0.3.3: Atlantis: https://github.com/hyperledger-solang/solang/pull/1573

Human semantic review and a current open+closed upstream search are required before counting this as a new bug.
