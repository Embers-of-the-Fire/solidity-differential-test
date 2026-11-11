# Review finding-75a9ff8a2bb5d43c

Status: **survivor**; origin: `finding`

## Minimized/current spec

```solidity
pragma solidity >=0.8.0;

contract IntDivShiftBoundaryCounts {
    uint256 public count;

    function sar8(int8 x, uint8 n) public returns (int8) {
        int8 r = x >> n;
        count++;
        return r;
    }

    function shr256(uint256 x, uint256 n) public returns (uint256) {
        uint256 r = x >> n;
        count++;
        return r;
    }
}
```

## Earliest divergence

```json
{
  "point": 3,
  "signature": "RETURN_MISMATCH|3|shr256|int\u2260int"
}
```

## Panel

```json
[
  {
    "category": "bug_candidate",
    "confidence": "high",
    "evidence": "Step 3 calls shr256(1, 256). In Solidity >=0.8.0, a right shift by 256 (>= bit width) must panic with Panic(0x11) due to shift-count overflow; the EVM side shows no valid return (recorded evm return 0). Solang on Polkadot instead completed the call and returned 1, i.e. it did not enforce the shift-count overflow check and effectively reduced the shift modulo the word size (1 >> 0 = 1).",
    "rationale": "The Solidity 0.8 semantics for shifts require a revert when the shift amount is >= the bit width of the operand. The EVM oracle reflects that panic, while solang silently returned 1, indicating missing runtime overflow checking for shift amounts on the Polkadot target. This is a semantic defect, not an environment, gas, packing, or projection artifact. No documented known-difference entry covers shift semantics, so it is not an intentional chain difference.",
    "historical_match_url": "",
    "cluster_hint": "solang missing shift-count overflow check: right shift by >= bit width should revert with Panic(0x11) but instead wraps the shift amount and returns a value"
  },
  {
    "category": "bug_candidate",
    "confidence": "medium",
    "evidence": "shr256(1, 256): EVM side yields 0 (consistent with a solc 0.8 panic on shift-by->=bit-width being projected as no return value), while solang on Polkadot returns 1, i.e. 1 >> (256 mod 256) = 1 >> 0. Solidity >=0.8.0 semantics require a panic (0x11) when the shift amount is >= the type width; the raw EVM SHR opcode masks the count to 8 bits, which is exactly the value 1 solang returned.",
    "rationale": "Solidity 0.8 defines shifting a uint256 by 256 or more as an overflow panic, and solc emits an explicit check; the Polkadot result of 1 indicates solang lowered the shift without the width guard, effectively performing a modulo-256 shift count. This is a genuine semantic deviation from documented Solidity behavior rather than a chain-environment or projection artifact. The EVM-side 0 is likely the oracle's encoding of the revert, so it is worth verifying the raw revert data, but the solang return of 1 is not defensible under Solidity semantics.",
    "historical_match_url": "",
    "cluster_hint": "solang missing shift-amount >= bit-width panic check on Polkadot target (shift count treated as modulo width instead of reverting)"
  }
]
```

## Adversarial review

```json
{
  "rebuttal_succeeds": false,
  "category": "bug_candidate",
  "evidence": "Step 3 calls shr256(1, 256). Under Solidity >=0.8.0 semantics, a uint256 right shift by an amount greater than or equal to 256 must trigger an arithmetic panic (Panic(0x11)), while the Polkadot result 1 is exactly the raw machine-style result 1 >> (256 mod 256) = 1 >> 0. The EVM-side dry-run value 0 is plausibly an oracle placeholder for a reverting call rather than a successful return, but that only affects classification of the EVM record; it does not make solang's successful return of 1 conform to Solidity semantics.",
  "rationale": "The mismatch is not covered by the documented environment-value or gas-metering differences, and none of the supplied historical records describe shift-count semantics. A compiler accepting `pragma solidity >=0.8.0` must implement the shift-amount overflow check unless the operation is in an `unchecked` block, which this source is not. The strongest remaining objection is an oracle encoding artifact for the EVM revert, but the Polkadot side's non-reverting wrap-like behavior is independently evidence of a solang semantic defect.",
  "historical_match_url": ""
}
```

## Potentially relevant historical records

- Thread 'main' panicked  error when compiling call with seeds: https://github.com/hyperledger-solang/solang/issues/1028
- Solang should not ask functions that contain `address.call` to be declared as view: https://github.com/hyperledger-solang/solang/issues/997
- functions that use .call() should be not allowed in view functions: https://github.com/hyperledger-solang/solang/pull/1338
- Allow seeds to be passed into functions as string[] or string[][]: https://github.com/hyperledger-solang/solang/pull/1547
- v0.3.2 Brasília: https://github.com/hyperledger-solang/solang/pull/1496
- v0.3.3: Atlantis: https://github.com/hyperledger-solang/solang/pull/1573
- [Snyk] Upgrade @solana/spl-token from 0.3.8 to 0.3.9: https://github.com/hyperledger-solang/solang/pull/1607
- CHANGELOG v0.3.2: 

Human semantic review and a current open+closed upstream search are required before counting this as a new bug.
