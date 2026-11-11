# Review finding-d126b12cf3e3839a

Status: **survivor**; origin: `finding`

## Minimized/current spec

```solidity
pragma solidity >=0.8.0;
contract Single {
    uint256 public result;
    uint256 public direct;
    function f(uint256 x) public returns (uint256) {
        return x - 200;
    }
    function g(uint256 x) public returns (uint256) {
        uint256 r = this.f(x);
        result = r;
        return r;
    }
    function h(uint256 x) public {
        direct = this.f(x);
    }
}
```

## Earliest divergence

```json
{
  "point": 2,
  "signature": "STATUS_MISMATCH|2|h|success\u2260error"
}
```

## Panel

```json
[
  {
    "category": "bug_candidate",
    "confidence": "medium",
    "evidence": "Step 2 calls h(250), which computes this.f(250) = 250-200 = 50 with no arithmetic underflow under Solidity 0.8 checked math; EVM dry-run and committed status are 'success' with storage {direct: 50} (nonzero_entries=1, value '50'). Polkadot dry-run returns status 'error' with a large nested DispatchError-style blob (multiple repeated account-id patterns '8eaf0415...4794f26a48', indicating nested call frames) and the committed tx reverts, leaving storage count 0. Step 1 g(0) shows no divergence, so both chains revert the genuine underflow 0-200 identically; the divergence is isolated to a semantically well-defined succeeding self-call. No env-value source markers (gasleft/block.*/tx.*) are present and gas comparison is disabled, so the documented known differences do not apply. The storage-count mismatch is downstream of the revert (direct never written), not an independent packing/endianness artifact.",
    "rationale": "An external self-call this.f(x) with no underflow reverting on pallet-contracts while succeeding on EVM points at a real semantic defect in solang's substrate external-call dispatch/revert propagation for self-calls, possibly triggered by state after the prior reverted self-call in step 1; the nested-frame error blob supports failure inside the internal call plumbing rather than in the arithmetic. This is not the historical contract-type-name call issue (#1007/PR #1011, which concerned Base.f() and was fixed) nor the large-constant arithmetic bug #1507. I cannot fully decode the revert blob, and cross-transaction state carryover via the harness is a possible alternative explanation, so confidence is medium rather than high; a minimal repro isolating h(250) without the prior g(0) revert would confirm.",
    "historical_match_url": "",
    "cluster_hint": "solang substrate external self-call (this.f) reverts at runtime for non-underflowing input; suspect self-call dispatch/revert propagation after a prior reverted self-call"
  },
  {
    "category": "bug_candidate",
    "confidence": "medium",
    "evidence": "Step 2 calls h(250), which computes this.f(250) = 250 - 200 = 50 with no underflow; EVM commits successfully and storage count shows 1 nonzero entry with value 50, while Polkadot dry-run returns an error and the committed tx reverts, leaving 0 nonzero entries. The revert blob contains a nested module error (repeating '010308160000...' inside the outer '030816000000...' payload with embedded account IDs), indicating the inner external self-call itself trapped/failed and propagated. The underflow case (g(0), step 0) matched on both chains, so the divergence is specifically the non-underflowing external self-call h(250).",
    "rationale": "Solidity semantics for h(250) are unambiguous: this.f(250) = 50, assignment to `direct` must succeed, matching solc/anvil exactly. The revert is not explained by intentional chain differences (no env values or gas involved; gas oracle off, no value transfer), and the storage mismatch reflects the revert rather than a count-mode packing/endianness artifact since the EVM side holds a single uint256 value 50. The pattern points at solang's substrate-target lowering of `this.f(x)` external self-calls (dispatch/reentrancy/return-data handling) trapping at runtime. Historical record #1007/#1011 concerns calls via contract type name (a compile-time issue), not runtime self-calls, so it is not a match; the nested-error blob suggests the inner call failed independently of the outer frame.",
    "historical_match_url": "",
    "cluster_hint": "external self-call via `this.f(x)` reverts on Polkadot for a non-underflowing input; nested module error propagates from the inner self-call"
  }
]
```

## Adversarial review

```json
{
  "rebuttal_succeeds": false,
  "category": "bug_candidate",
  "evidence": "The divergent step (h(250)) is semantically unambiguous under Solidity 0.8 checked arithmetic: this.f(250)=50 cannot underflow, there is no value transfer or access control, and EVM dry-run and committed status both succeed with storage {direct:50}. The control step g(0) exercises the same external self-call path with a genuine underflow and matches on both chains (both revert), isolating the defect to the succeeding self-call rather than to arithmetic or setup. The documented known differences do not apply: no env-value source markers (gasleft/block.*/tx.*) appear in the source, gas comparison is disabled, and the primary divergence is STATUS/TX_STATUS \u2014 not a storage-count artifact (the storage count 0 vs 1 is fully explained by the revert, and the EVM side holds a single plain uint256, ruling out packing/endianness count-mode noise). The revert blob contains a nested dispatch-style error with repeated embedded account IDs, consistent with failure inside nested call-frame plumbing rather than an outer-frame oracle failure, and it appears in both dry-run and committed forms, so it is not a dry-run-only oracle artifact. Historical records do not match: #1007/PR #1011 is a compile-time issue for calls via contract type name (Base.f), fixed; #1507 concerns large-constant multiplication (>=0x200000001), not a small checked subtraction; the span/Snyk records are irrelevant.",
  "rationale": "Every documented known difference and every historical record fails to explain a successful, value-free, non-underflowing external self-call reverting on pallet-contracts while succeeding on EVM, with a matched underflow control case on the same code path. The strongest remaining counter-hypothesis \u2014 cross-transaction state carryover in the harness from the reverted step-1 call \u2014 is speculative, would itself be an undocumented harness defect, and is testable with a minimal repro of h(250) in isolation; it does not reclassify the finding, only bounds confidence at medium. The evidence survives scrutiny as a genuine solang substrate-target self-call dispatch/revert-propagation defect candidate.",
  "historical_match_url": ""
}
```

## Potentially relevant historical records

- Add Rename functionality: https://github.com/hyperledger-solang/solang/pull/1514
- [Snyk] Upgrade @coral-xyz/anchor from 0.28.0 to 0.29.0: https://github.com/hyperledger-solang/solang/pull/1589
- [Snyk] Upgrade @coral-xyz/anchor from 0.28.0 to 0.29.0: https://github.com/hyperledger-solang/solang/pull/1591
- [Snyk] Upgrade @solana/spl-token from 0.3.8 to 0.3.9: https://github.com/hyperledger-solang/solang/pull/1607
- Inconsistent behaviour when calling function via contract type name: https://github.com/hyperledger-solang/solang/issues/1007
- Scratch buffer data leakages : https://github.com/hyperledger-solang/solang/issues/1399
- Incorrect integer calculation: https://github.com/hyperledger-solang/solang/issues/1507
- Fix function calls via contract name: https://github.com/hyperledger-solang/solang/pull/1011

Human semantic review and a current open+closed upstream search are required before counting this as a new bug.
