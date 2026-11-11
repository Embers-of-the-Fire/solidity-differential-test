# Review finding-22735298647112c0

Status: **survivor**; origin: `finding`

## Minimized/current spec

```solidity
pragma solidity >=0.8.0;

contract Base {
    function f(uint256 x) public virtual returns (uint256) {
        return 100 + x;
    }
}

contract Child is Base {
    function f(uint256 x) public override returns (uint256) {
        return 200 + x;
    }

    function f(uint256 x, uint256 y) public returns (uint256) {
        return 300 + x + y;
    }

    function runDispatch(uint256 x) public returns (uint256) {
        return this.f(x);
    }
}

```

## Earliest divergence

```json
{
  "point": "compile",
  "signature": "COMPILE_ASYMMETRY|compile||solang-rejects"
}
```

## Panel

```json
[
  {
    "category": "bug_candidate",
    "confidence": "high",
    "evidence": "solc accepted the source, while solang rejected line 19 (`return this.f(x);`) with both `function call can be resolved to multiple functions` and `cannot find overloaded function which matches signature`. The listed candidates include Base.f(uint256) and Child.f(uint256), even though the latter declares `override` and should replace the inherited implementation rather than create a second same-signature candidate; solang also considered Child.f(uint256,uint256), producing `function expects 2 arguments, 1 provided`.",
    "rationale": "This is a compile-time semantic divergence on standard Solidity: an overridden function should not remain an ambiguous base-contract overload, and `this.f(x)` should resolve unambiguously to the overriding Child function. The behavior is not explained by chain environment, oracle projection, storage representation, or gas accounting because compilation itself fails in solang. The rejection prevents execution of an otherwise valid contract and indicates incorrect virtual/override overload-resolution handling.",
    "historical_match_url": "https://github.com/hyperledger-solang/solang/issues/780",
    "cluster_hint": "override and virtual base overloads treated as duplicate dispatch candidates during external `this.f` resolution"
  },
  {
    "category": "bug_candidate",
    "confidence": "high",
    "evidence": "solc accepts the source and compiles successfully; solang rejects at line 19 `return this.f(x)` reporting 'function call can be resolved to multiple functions' with two candidate functions listed: Base.f(uint256) at line 4 and Child.f(uint256) at line 10, which have identical signatures because the child overrides the base. Per Solidity semantics the override fully replaces the base function in the derived contract's callable set, so `this.f(x)` unambiguously resolves to Child.f(uint256) and returns 200+x. solang instead treats both the base and overriding declaration as independent candidates, breaking overload resolution.",
    "rationale": "The divergence is a compile-time rejection by solang of code that is valid per Solidity's inheritance/override semantics. Because the child function overrides the base one, only one single-argument f exists in the contract; solang's resolution incorrectly retains the hidden base declaration as a candidate. This is a genuine name-resolution/overload bug in solang, not a chain, oracle, or intentional difference, and it blocks even executing the dispatch test. The third overload error (2-arg f candidate) is a cascade of the same failed resolution.",
    "historical_match_url": "https://github.com/hyperledger-solang/solang/issues/780",
    "cluster_hint": "override-hiding not applied during overload resolution: overridden base function remains a resolution candidate, causing 'resolved to multiple functions' on this.f dispatch"
  }
]
```

## Adversarial review

```json
{
  "rebuttal_succeeds": false,
  "category": "bug_candidate",
  "evidence": "solang rejects `this.f(x)` and explicitly lists both `Base.f(uint256)` at line 4 and `Child.f(uint256)` at line 10 as candidates, even though the latter is declared `override` and has the identical signature; solc accepts the same source. The diagnostic also lists `Child.f(uint256,uint256)` as an incompatible candidate. This is a compile-time asymmetry at line 19, before any chain-environment, oracle, storage, or gas accounting can matter.",
  "rationale": "Under Solidity inheritance semantics, the overriding `Child.f(uint256)` replaces the inherited base implementation, so external dispatch through `this.f(x)` should resolve to that single one-argument function. The diagnostic shows solang failed to hide the overridden base declaration during overload resolution, making this a plausible solang semantic-resolution defect rather than an intentional platform difference or runtime artifact. The mismatched later step names are a probe-quality concern, but they do not undermine the self-contained compile error. Issue #780 is only a closest historical overload-resolution reference, not proof that this exact override-dispatch case was already reported.",
  "historical_match_url": "https://github.com/hyperledger-solang/solang/issues/780"
}
```

## Potentially relevant historical records

- Add Rename functionality: https://github.com/hyperledger-solang/solang/pull/1514
- Inconsistent behaviour when calling function via contract type name: https://github.com/hyperledger-solang/solang/issues/1007
- Incorrect constructor inheritance: https://github.com/hyperledger-solang/solang/issues/1428
- Cannot find overloaded function: https://github.com/hyperledger-solang/solang/issues/780
- Fix function calls via contract name: https://github.com/hyperledger-solang/solang/pull/1011
- Support user defined operators (solc v0.8.19 feature): https://github.com/hyperledger-solang/solang/pull/1203
- Bugfix: Accessing virtual function selectors: https://github.com/hyperledger-solang/solang/pull/1447
- Bring import resolution in line w/ Solc's: https://github.com/hyperledger-solang/solang/pull/1487

Human semantic review and a current open+closed upstream search are required before counting this as a new bug.
