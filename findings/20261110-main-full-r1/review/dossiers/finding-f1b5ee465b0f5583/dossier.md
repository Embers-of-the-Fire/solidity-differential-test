# Review finding-f1b5ee465b0f5583

Status: **survivor**; origin: `finding`

## Minimized/current spec

```solidity
pragma solidity >=0.8.0;contract Child{uint256 public hits;uint256 public lastResult;function f(uint256 x)public returns(uint256){hits=x+1;return 200+x;}function g(uint256 x)public returns(uint256){return lastResult=this.f(x);}}
```

## Earliest divergence

```json
{
  "point": 0,
  "signature": "STATUS_MISMATCH|0|g|success\u2260error"
}
```

## Panel

```json
[
  {
    "category": "bug_candidate",
    "confidence": "medium",
    "evidence": "EVM: g(0) succeeds, storage = [1, 200] exactly matching semantics (hits = 0+1, lastResult = 200+0). Polkadot: top-level tx reverts with a nested pallet-contracts error blob (0x030816... containing nested call data with alice's address d43593c... and inner fields), and storage count = 0, i.e. nothing was committed. The only nontrivial operation is the external self-call `this.f(x)` inside g; the revert payload shape indicates the inner call failed on pallet-contracts while the identical code succeeds on anvil. The source contains none of the env-value markers (gasleft/block.*/tx.*), so known-difference env-values and gas-metering do not apply.",
    "rationale": "This is plain, valid Solidity: an external self-call `this.f(x)` whose selector dispatch must succeed and mutate `hits`, then assign the return to `lastResult`. solc-on-EVM produces exactly the expected state, so the program and oracle projection are sound; solang-on-Polkadot reverts during the nested call. The hex error is consistent with a failed inner dispatch/call (selector or callee-address handling for `this`-calls) rather than an environment or metering artifact. pallet-contracts permits self-calls, so a revert here points at a solang codegen/dispatch defect. Confidence is medium rather than high because the opaque revert blob cannot be decoded to a precise reason from the evidence alone.",
    "historical_match_url": "",
    "cluster_hint": "solang mishandles external self-call dispatch (`this.f(x)`), causing the nested call to revert on pallet-contracts (selector or self-address resolution defect)"
  },
  {
    "category": "bug_candidate",
    "confidence": "medium",
    "evidence": "g(0) succeeds on EVM: hits=1, lastResult=200 (2 nonzero storage entries). On Polkadot the transaction traps (pallet-contracts DispatchError module 08 error 0x16-style blob, not a Solidity revert reason) and rolls back to 0 nonzero storage entries. Source is a valid, minimal contract: g does `return lastResult=this.f(x)` and f does `hits=x+1; return 200+x;` \u2014 no environment reads, no gas dependency, no revert path in the program.",
    "rationale": "The program has no revert condition, so the Polkadot trap is not explained by documented chain-environment differences. The large structured error blob is characteristic of a pallet-contracts ContractTrapped rather than a Solidity revert, pointing to a runtime dispatch/call defect for the external self-call `this.f(x)` in solang's substrate codegen. The storage mismatch is a downstream consequence of the rollback, not an independent issue. Confidence is medium because pallet-contracts self-calls do add a call frame and a chain-level call failure cannot be fully excluded without the decoded error.",
    "historical_match_url": "",
    "cluster_hint": "runtime trap on external self-call via `this` (selector dispatch / internal call trampoline), rollback wipes all state"
  }
]
```

## Adversarial review

```json
{
  "rebuttal_succeeds": false,
  "category": "bug_candidate",
  "evidence": "The source is a valid, minimal contract with no revert path: f sets hits=x+1 and returns 200+x; g assigns lastResult=this.f(x). On anvil, g(0) succeeds and storage exactly matches the semantics ([1, 200]), so the probe and the solc oracle projection are sound. On pallet-contracts both the dry-run and the committed transaction fail with a structured pallet error blob and storage rolls back to zero entries. The source contains none of the env-values markers (no gasleft/block.*/tx.*), so the documented env-values difference cannot apply. The gas-metering known difference covers GAS_MISMATCH observations; here gas is explicitly disabled in the oracle (\"gas\": false) and the failure is a trap/revert with full rollback, not a gas-quantity disagreement, so that rationale does not cover this divergence either.",
  "rationale": "The strongest rebuttal \u2014 that the inner-call trap reflects an incomparable gas model or a by-design chain environment difference \u2014 fails because the observation is a hard status/trap mismatch with zero committed storage, not a gas or environment-value delta, and the program has no revert branch for a legitimate semantic difference to trigger. The nested blob shows the outer frame constructed and dispatched an inner self-call which then failed on pallet-contracts while identical code succeeds on EVM, which is consistent with a solang substrate-codegen defect in external self-call dispatch (selector or self-address resolution, or gas/flags forwarding for the nested call) rather than an oracle artifact \u2014 the storage mismatch is clearly downstream of the rollback. The closest historical record (#1007) concerns static calls via contract type names and a compile-time panic, which is a different construct and a different failure phase, so it is not a rediscovery.",
  "historical_match_url": ""
}
```

## Potentially relevant historical records

- Add Rename functionality: https://github.com/hyperledger-solang/solang/pull/1514
- Inconsistent behaviour when calling function via contract type name: https://github.com/hyperledger-solang/solang/issues/1007
- Support user defined operators (solc v0.8.19 feature): https://github.com/hyperledger-solang/solang/pull/1203
- [Snyk] Upgrade @coral-xyz/anchor from 0.28.0 to 0.29.0: https://github.com/hyperledger-solang/solang/pull/1589
- [Snyk] Upgrade @coral-xyz/anchor from 0.28.0 to 0.29.0: https://github.com/hyperledger-solang/solang/pull/1591
- [Snyk] Upgrade @solana/spl-token from 0.3.8 to 0.3.9: https://github.com/hyperledger-solang/solang/pull/1607
- Substrate: Event decoding does not match `ink!`: https://github.com/hyperledger-solang/solang/issues/1373
- Scratch buffer data leakages : https://github.com/hyperledger-solang/solang/issues/1399

Human semantic review and a current open+closed upstream search are required before counting this as a new bug.
