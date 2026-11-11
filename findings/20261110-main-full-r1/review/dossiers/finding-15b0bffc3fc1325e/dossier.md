# Review finding-15b0bffc3fc1325e

Status: **survivor**; origin: `finding`

## Minimized/current spec

```solidity
pragma solidity >=0.8.0;

contract IntDivCaptureBeforeCount {
    int8 public min8;
    int16 public min16;
    int64 public min64;
    int8 public r8;
    
    
    uint256 public count;

    constructor() {
        min8 = type(int8).min;
        min16 = type(int16).min;
        min64 = type(int64).min;
    }

    function div8() public returns (int8) {
        int8 r = min8 / int8(-1);
        r8 = r;
        count++;
        return r;
    }

    

    
}
```

## Earliest divergence

```json
{
  "point": 0,
  "signature": "STATUS_MISMATCH|0|div8|revert\u2260success"
}
```

## Panel

```json
[
  {
    "category": "bug_candidate",
    "confidence": "high",
    "evidence": "Step 0 div8(): EVM dry-run and committed status are 'revert' (solc enforces checked arithmetic; type(int8).min / int8(-1) panics 0x12 in Solidity >=0.8), while Polkadot status is 'success'. Polkadot storage shows r8 = -128 and count = 1, i.e. solang executed min8 / -1 and returned -128 (two's-complement wraparound) with no overflow check and no revert. The STORAGE_MISMATCH itself is partly an oracle projection artifact: EVM packs min8/min16/min64 into one slot (single nonzero value 154742504910672534370779264) whereas solang stores 5 separate cells (-128, -128, -32768, -9223372036854775808, 1), exactly the packing/count-mode conflation noted in the rubric \u2014 but the status divergence is independent of that.",
    "rationale": "Solidity >=0.8 semantics require a Panic(0x12) revert for signed division overflow of INT_MIN / -1; solc reverts as expected. Solang committing the transaction and storing the wrapped result -128 indicates a missing checked-arithmetic overflow guard for signed division in solang's Polkadot codegen, which is a real semantic defect, not an intentional chain difference (the documented env/gas known differences do not apply; no gas or env markers here). The test is valid: constructor args are well-formed and the probe isolates exactly this operation.",
    "historical_match_url": "",
    "cluster_hint": "solang missing signed-division overflow check (int.min / -1 should panic 0x12, instead wraps and succeeds)"
  },
  {
    "category": "bug_candidate",
    "confidence": "high",
    "evidence": "Step 0 call div8(): EVM dry-run and committed status = revert (solc enforces Solidity 0.8 checked arithmetic: type(int8).min / -1 overflows and must panic), while Polkadot status = success. Polkadot storage then shows r8 = -128 and count = 1, i.e. solang wrapped the result to -128 and committed state instead of reverting. The EVM storage (single nonzero entry 154742504910672534370779264 = constructor-initialized packed min values, no r8/count writes) is consistent with the revert; the count-mode STORAGE_MISMATCH is a downstream artifact of the status divergence plus per-variable cell layout, not an independent issue.",
    "rationale": "Under Solidity >=0.8 semantics, signed division of the minimum value by -1 is an arithmetic overflow that must revert with a panic; solc does revert. Solang instead returns success with the two's-complement wrapped value -128 persisted, indicating the overflow check for signed division (SDIV min/-1) is missing or elided in solang's Polkadot codegen. This is not an environment value difference, gas modeling, or revert-wording artifact \u2014 it is a genuine semantic defect on a deterministic pure-arithmetic operation. No documented known difference covers arithmetic overflow checks, and none of the cached upstream records address division overflow.",
    "historical_match_url": "",
    "cluster_hint": "solang missing checked-arithmetic revert for signed division overflow (int min / -1 wraps to min instead of panicking)"
  }
]
```

## Adversarial review

```json
{
  "rebuttal_succeeds": false,
  "category": "bug_candidate",
  "evidence": "No documented known difference covers arithmetic semantics: neither 'env-values' (gasleft/block.* markers, absent here) nor 'gas-metering' applies, and the oracle has gas disabled. The status divergence is independent of the storage-packing projection artifact the panels correctly flagged: EVM dry-run and committed status are both 'revert' (solc's inserted checked-arithmetic guard panics 0x12 for INT_MIN / -1, per Solidity >=0.8 semantics the pragma declares), while Polkadot commits with r8 = -128 and count = 1, proving solang's Polkadot codegen wrapped the SDIV result and persisted state. It is not a solc-side defect: solc's behavior matches the specified checked-arithmetic semantics. It is not a rediscovery: none of the cached upstream records (#1007 contract-type-name calls, #1028 seeds panic, #641 llvm-dis, #731 stack overflow in cast, #813 inkwell type panic, #997 view warning, #1514 spans, #1573 release notes) address division overflow checks. The probe is valid: deterministic pure arithmetic, well-formed constructor, no env or value dependencies, and the mutant origin does not invalidate the semantics under test.",
  "rationale": "The strongest rebuttal available is that solang intentionally targets different runtime semantics, but solang explicitly aims for Solidity compatibility, and Solidity >=0.8 mandates a Panic(0x12) revert for signed division overflow; a silent two's-complement wrap that commits state is a missing overflow guard in solang's codegen, not an intentional platform difference or oracle artifact. The STORAGE_MISMATCH is indeed partly a packing/cell-layout artifact, but the dry-run and committed STATUS_MISMATCH at step 0 is the load-bearing evidence and survives every filtering rule provided. Historical records show solang has a pattern of arithmetic/codegen crashes and missing checks, but none match this specific defect, so it is not a rediscovery.",
  "historical_match_url": ""
}
```

## Potentially relevant historical records

- Add Rename functionality: https://github.com/hyperledger-solang/solang/pull/1514
- v0.3.3: Atlantis: https://github.com/hyperledger-solang/solang/pull/1573
- Inconsistent behaviour when calling function via contract type name: https://github.com/hyperledger-solang/solang/issues/1007
- Thread 'main' panicked  error when compiling call with seeds: https://github.com/hyperledger-solang/solang/issues/1028
- llvm-dis fails to disassemble bitcode file generated by Solang for a smart contract: https://github.com/hyperledger-solang/solang/issues/641
- Error in sema parsing contract: https://github.com/hyperledger-solang/solang/issues/731
- Inkwell crashes when building for Solana and Substrate: https://github.com/hyperledger-solang/solang/issues/813
- Solang should not ask functions that contain `address.call` to be declared as view: https://github.com/hyperledger-solang/solang/issues/997

Human semantic review and a current open+closed upstream search are required before counting this as a new bug.
