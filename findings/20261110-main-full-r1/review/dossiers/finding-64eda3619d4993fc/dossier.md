# Review finding-64eda3619d4993fc

Status: **survivor**; origin: `finding`

## Minimized/current spec

```solidity
pragma solidity >=0.8.0;

contract IntDivOverflowWidthSweep {
    int16 public min16;
    int64 public min64;
    int128 public min128;
    int256 public min256;
    uint256 public count;

    constructor() {
        min16 = type(int16).min;
        min64 = type(int64).min;
        min128 = type(int128).min;
        min256 = type(int256).min;
    }

    function div16() public returns (int16) {
        int16 r = min16 / int16(-1);
        count++;
        return r;
    }

    

    

    

    

    
}
```

## Earliest divergence

```json
{
  "point": 0,
  "signature": "STATUS_MISMATCH|0|div16|revert\u2260success"
}
```

## Panel

```json
[
  {
    "category": "bug_candidate",
    "confidence": "high",
    "evidence": "div16 computes min16 / int16(-1) = (-32768) / (-1) = 32768, which exceeds int16 max (32767). Solidity 0.8 semantics require a revert for this division overflow, and solc/anvil does revert. Polkadot (solang) reports success and count increments to 1, so solang computed the result without a width overflow check. The storage diff is consistent: polkadot shows count=1 plus the four negative minima, while evm shows only storage written before the reverting call.",
    "rationale": "The divergence is a genuine semantic defect: solang fails to enforce the checked-arithmetic rule that type(intN).min / -1 must revert for narrow signed types like int16. A plausible mechanism is that solang widens int16 to a larger internal integer, where 32768 fits, and only checks overflow against the widened width rather than the declared 16-bit width. The storage-count mismatch is an oracle projection artifact (packing of narrow signed cells) and is secondary to the authoritative status mismatch.",
    "historical_match_url": "",
    "cluster_hint": "solang missing width-scaled overflow check for signed division INT_MIN / -1 on narrow integer types (int16)"
  },
  {
    "category": "bug_candidate",
    "confidence": "medium",
    "evidence": "div16 computes min16 / int16(-1) where min16 = type(int16).min = -32768; Solidity 0.8 semantics require a Panic(0x11) on signed division overflow since 32768 does not fit in int16. EVM (solc) reverts as expected, while Polkadot (solang) reports success and count increments to 1, proving execution continued past the overflowing division. The storage-count diff is noisy (EVM side shows only 2 nonzero entries despite four nonzero min constants, and a garbled large value), consistent with packing/projection artifacts, but the status mismatch is unambiguous.",
    "rationale": "The divergence is a genuine semantic one: solang on Polkadot fails to trap the INT_MIN / -1 division overflow that Solidity 0.8 mandates as a runtime panic, while solc correctly reverts. There is no documented chain-environment or oracle-projection rationale for a success-vs-revert split on pure arithmetic. The Soroban width-rounding record is Soroban-only and irrelevant here. Medium rather than high confidence because the storage projection is unreliable in count mode and no return value from div16 is recorded to confirm the wrapped result.",
    "historical_match_url": "https://github.com/hyperledger-solang/solang/pull/1496",
    "cluster_hint": "missing runtime overflow check for signed division INT_MIN / -1 (narrow int16 cell) on Polkadot target"
  }
]
```

## Adversarial review

```json
{
  "rebuttal_succeeds": false,
  "category": "bug_candidate",
  "evidence": "div16 computes type(int16).min / int16(-1) = -32768 / -1 = 32768, which is not representable in int16. The Solidity 0.8 specification mandates a Panic(0x11) revert for this signed-division overflow, and solc/anvil reverts exactly as specified. Solang on Polkadot reports success with count incremented to 1, meaning execution continued past the overflowing operation. This status divergence is deterministic, occurs in pure arithmetic with no dependence on chain environment values (no gasleft, block.*, tx.* markers), and none of the documented known-difference records (env-values, gas-metering) apply. The storage-count mismatch is a projection artifact (EVM shows only 2 nonzero entries for four min constants, indicating count-mode packing noise), but it is secondary to the authoritative revert-vs-success split. The only plausible rebuttal is rediscovery via the v0.3.2 changelog line about math overflow fixes, but that entry names the negate operator specifically and 'other math overflow fixes' is not documented as covering signed-division INT_MIN/-1 on narrow widths; without harness version evidence showing a pre-0.3.2 solang, this remains an unrediscovered or unfixed defect.",
  "rationale": "The revert-vs-success divergence on a spec-mandated overflow (Solidity 0.8 requires Panic for INT_MIN/-1) cannot be explained as an oracle artifact, intentional platform difference, or solc defect \u2014 solc behavior matches the language specification. The most plausible mechanism is that solang widens int16 to an internal larger integer, computes 32768 successfully, and fails to apply the overflow check at the declared 16-bit width. The sole escape hatch is version-dependent rediscovery, which the evidence does not establish.",
  "historical_match_url": "https://github.com/hyperledger-solang/solang/pull/1496"
}
```

## Potentially relevant historical records

- Implement Soroban integer width rounding feature (#1805): https://github.com/hyperledger-solang/solang/pull/1810
- Inconsistent behaviour when calling function via contract type name: https://github.com/hyperledger-solang/solang/issues/1007
- llvm-dis fails to disassemble bitcode file generated by Solang for a smart contract: https://github.com/hyperledger-solang/solang/issues/641
- Inkwell crashes when building for Solana and Substrate: https://github.com/hyperledger-solang/solang/issues/813
- v0.2.3 Geneva: https://github.com/hyperledger-solang/solang/pull/1256
- v0.3.2 Brasília: https://github.com/hyperledger-solang/solang/pull/1496
- Add Rename functionality: https://github.com/hyperledger-solang/solang/pull/1514
- v0.3.3: Atlantis: https://github.com/hyperledger-solang/solang/pull/1573

Human semantic review and a current open+closed upstream search are required before counting this as a new bug.
