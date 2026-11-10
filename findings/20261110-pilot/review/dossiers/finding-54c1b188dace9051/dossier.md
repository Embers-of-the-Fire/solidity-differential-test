# Review finding-54c1b188dace9051

Status: **survivor**; origin: `finding`

## Minimized/current spec

```solidity
pragma solidity >=0.8.0;

contract RevertProbe {
    uint public attempts;
    error MyError(uint code, string why);

    

    function trigger(uint sel) public {
        attempts++;
        if (sel == 0) {
            uint a = 0;
            a -= 1;
        } else if (sel == 1) {
            uint b = 1;
            uint c = 5 / (b - 1);
        } else if (sel == 2) {
            require(false, "custom revert message");
        } else if (sel == 3) {
            assert(false);
        } else if (sel == 4) {
            revert MyError(42, "boom");
        } else if (sel == 5) {
            uint[] memory m;
            m[3] = 1;
        } else {
            revert("fallback reason");
        }
    }
}
```

## Earliest divergence

```json
{
  "point": 0,
  "signature": "STATUS_MISMATCH|0|trigger|revert\u2260success"
}
```

## Panel

```json
[
  {
    "category": "bug_candidate",
    "confidence": "medium",
    "evidence": "Step 0 calls trigger(0), which executes `uint a = 0; a -= 1;` \u2014 a subtraction underflow that Solidity 0.8 semantics require to panic/revert. EVM status=revert (correct), Polkadot status=success with attempts incremented to 1 (nonzero storage entry), indicating the underflow silently wrapped to 2^256-1 instead of reverting.",
    "rationale": "Both chains compile the same source with checked arithmetic expected. The EVM correctly reverts on the underflow while solang on Polkadot commits the transaction with state mutation (attempts=1), which is only possible if the underflow check was not enforced. This is a genuine semantic divergence in arithmetic overflow/underflow handling, not an environment, gas, or revert-encoding difference, since the Polkadot side reports outright success rather than an equivalent revert.",
    "historical_match_url": "https://github.com/hyperledger-solang/solang/pull/1496",
    "cluster_hint": "solang fails to trap on uint underflow in compound subtraction (`a -= 1`), wrapping instead of panicking; adjacent to the v0.3.2 overflow-checking fixes but distinct from negate-operator case"
  },
  {
    "category": "bug_candidate",
    "confidence": "high",
    "evidence": "For trigger(0), the source executes attempts++ and then `uint a = 0; a -= 1;`. EVM dry-run and committed status are both `revert`, with zero nonzero storage entries after rollback. Polkadot reports `success` and persists one nonzero storage value, consistent with `attempts == 1`.",
    "rationale": "Solidity 0.8 semantics require checked arithmetic, so subtracting 1 from a zero `uint` must panic and revert, including rolling back the preceding `attempts++`. The observed Polkadot success and persisted state therefore indicate that the underflow was not detected or did not cause transaction failure. The storage-count projection is not the primary basis for the finding; the independent status mismatch establishes the semantic divergence.",
    "historical_match_url": "https://github.com/hyperledger-solang/solang/pull/1496",
    "cluster_hint": "unchecked uint underflow in compound subtraction allows execution to succeed and persist prior state"
  }
]
```

## Adversarial review

```json
{
  "rebuttal_succeeds": false,
  "category": "bug_candidate",
  "evidence": "EVM dry-run and committed status are both `revert` with zero nonzero storage entries, consistent with checked-arithmetic rollback of `attempts++`. Polkadot reports committed `success` with one persisted nonzero storage value (attempts==1). Since pallet-contracts rolls back contract storage on revert/trap, the persisted increment is only explainable if the `a -= 1` underflow neither trapped nor reverted \u2014 i.e., it silently wrapped. The known Polkadot revert-encoding difference (PR #1449) explains how a revert is reported, not whether it happens; here the state mutation proves no revert occurred.",
  "rationale": "The strongest rebuttal available is that this is a rediscovery of the v0.3.2 overflow-checking fixes (PR #1496), which addressed the negate operator and 'other math overflow fixes'. However, that PR was merged and presumably fixed compound-assignment underflow along with other operators; a still-failing `-=` on a current build would be a residual gap rather than a duplicate of the fixed negate case. There is no env-value, gas, or oracle-status explanation for persisted storage on the Polkadot side. The evidence survives scrutiny as a genuine solang arithmetic-checking divergence.",
  "historical_match_url": "https://github.com/hyperledger-solang/solang/pull/1496"
}
```

## Potentially relevant historical records

- Polkadot: Reverts return encoded error data: https://github.com/hyperledger-solang/solang/pull/1449
- Reserved keywords collision in Yul assembly: https://github.com/hyperledger-solang/solang/issues/639
- "unrecognised token '.' when "if (error.length > 0)" : https://github.com/hyperledger-solang/solang/issues/938
- v0.3.3: Atlantis: https://github.com/hyperledger-solang/solang/pull/1573
- Inconsistent behaviour when calling function via contract type name: https://github.com/hyperledger-solang/solang/issues/1007
- Memory OOB access in try-catch: https://github.com/hyperledger-solang/solang/issues/1292
- v0.3.2 Brasília: https://github.com/hyperledger-solang/solang/pull/1496
- fix(soroban): reject unsupported ABI types before codegen: https://github.com/hyperledger-solang/solang/pull/1903

Human semantic review and a current open+closed upstream search are required before counting this as a new bug.
