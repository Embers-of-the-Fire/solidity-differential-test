# Review finding-874f80ca055771a0

Status: **survivor**; origin: `finding`

## Minimized/current spec

```solidity
pragma solidity >=0.8.0;

contract CryptoHashWidthProbe {
    bytes32 public k16;
    bytes32 public e16;
    bytes32 public k32;
    bytes32 public e32;
    bytes32 public k64;
    bytes32 public e64;

    function set(uint16 a, uint32 b, uint64 c) public {
        k16 = keccak256(abi.encodePacked(a));
        e16 = keccak256(abi.encode(a));
        k32 = keccak256(abi.encodePacked(b));
        e32 = keccak256(abi.encode(b));
        k64 = keccak256(abi.encodePacked(c));
        e64 = keccak256(abi.encode(c));
    }
}

```

## Earliest divergence

```json
{
  "point": 0,
  "signature": "STORAGE_MISMATCH|0|set|multiset(count)"
}
```

## Panel

```json
[
  {
    "category": "bug_candidate",
    "confidence": "high",
    "evidence": "EVM storage (6 nonzero entries): one copy each of -10446551254174361523047807172649316427104996572770475611352622933819532303284, 38292439343987868037672198288784556730787963328266909981497454499372014593944, 500549258012437878224561338362079327067368301550791134293299473726337612750 (the three distinct keccak256(abi.encodePacked(x)) hashes of 2-, 4-, and 8-zero-byte inputs), plus 3x 18569430475105882587588266137607568536673111973893317399460219858819262702947 (keccak256 of 32 zero bytes, identical for e16=e32=e64). Polkadot storage has exactly 2 copies of each of the three distinct values: every k-slot equals its paired e-slot (k16==e16, k32==e32, k64==e64), i.e. solang produced the same hash for packed and standard encoding.",
    "rationale": "With args (0,0,0), Solidity semantics require abi.encodePacked(uint16(0)) to hash 2 zero bytes while abi.encode(uint16(0)) hashes 32 zero bytes; solc reflects this with three distinct packed hashes and three identical encode hashes. Solang collapsing k and e pairs means it is encoding the single narrow integer as a 32-byte padded word inside abi.encodePacked (or otherwise aliasing packed to standard encoding), a real semantic defect, not an environment/gas/known-difference artifact. The negative values in the oracle output are just signed interpretation of bytes32 by the storage-count projection and do not explain the duplicated-hash pattern. The supplied historical records (encodeCall argument parsing, BlindAuction codegen panic) do not match this hashing/encoding behavior.",
    "historical_match_url": "",
    "cluster_hint": "solang computes keccak256(abi.encodePacked(x)) over the 32-byte ABI-padded encoding for a single narrow integer, so packed and encode hashes collide for uint16/uint32/uint64"
  },
  {
    "category": "bug_candidate",
    "confidence": "medium",
    "evidence": "EVM stores 18569430475105882587588266137607568536673111973893317399460219858819262702947 (= keccak256 of 32 zero bytes, 0x290decd9...) three times, matching the correct Solidity semantics: abi.encode(uint16/32/64 zero) pads to 32 bytes so e16==e32==e64, while k16/k32/k64 are the three distinct values -1044655..., 38292439..., 500549258.... Polkadot stores each of those three distinct packed-hash values exactly twice and never stores the padded-hash value at all, i.e. the e-slots got the same hash as the k-slots. Both chains show 6 nonzero entries, so all six slots were written and this is a content difference, not a storage-count projection artifact.",
    "rationale": "For input 0, the only way Polkadot's multiset contains the three packed-width hashes each duplicated and entirely lacks keccak256(32 zero bytes) is if solang encoded abi.encode(a) for a single narrow uint without 32-byte padding (i.e. identical to encodePacked), or reused the packed hash for the encode slot. That is a genuine Solidity semantic violation (abi.encode must left-pad to 32 bytes) unrelated to the documented env/gas known differences. Skeptical caveat: the signed-int rendering of bytes32 in count mode is odd, but three values match exactly across chains, so the projection is consistent and the divergence is real; I cannot fully exclude an upstream reporting overlap, hence medium confidence.",
    "historical_match_url": "",
    "cluster_hint": "solang abi.encode of a single narrow-width integer produces unpadded (packed-like) encoding, so keccak256(abi.encode(x)) == keccak256(abi.encodePacked(x)) for uint16/32/64"
  }
]
```

## Adversarial review

```json
{
  "rebuttal_succeeds": false,
  "category": "bug_candidate",
  "evidence": "Both chains write exactly 6 nonzero storage slots, but the multisets are disjoint in content: EVM stores keccak256 of 32 zero bytes (18569430475105882587588266137607568536673111973893317399460219858819262702947) three times for the e-slots plus three distinct packed-width hashes for the k-slots; Polkadot stores each packed-width hash exactly twice and never stores the 32-byte-padded hash. Since all six slots are written on both sides, the difference is in the hashed values, not in slot selection or an unwritten-slot artifact. The signed rendering of bytes32 by the count projection is consistent across chains (the packed-hash values match EVM exactly), so the projection is not the cause. None of the documented known differences (env values, gas metering) apply: no environment markers or gas comparison is involved, and none of the supplied historical records describe abi.encode padding or abi.encodePacked aliasing on the Polkadot target.",
  "rationale": "For solang to produce e16==k16, e32==k32, e64==e64 while still distinguishing the three packed widths, its abi.encode of a single uint16/uint32/uint64 must be omitting the mandatory 32-byte left-padding that Solidity specifies for standard encoding \u2014 a genuine compiler semantic defect, not an intentional platform difference, since abi.encode semantics are target-independent. I attempted rebuttals as storage-layout permutation, count-projection artifact, codec known difference (Borsh/SCALE apply to call data, not the abi.encode builtin), and rediscovery against the supplied records; all fail on the evidence above. The only residual uncertainty is whether an unsupplied upstream issue already tracks this, which lowers but does not eliminate confidence.",
  "historical_match_url": ""
}
```

## Potentially relevant historical records

- thread 'main' panicked while compiling BlindAuction from Solidity official website: https://github.com/hyperledger-solang/solang/issues/1076
- refactor src/codegen: https://github.com/hyperledger-solang/solang/pull/1923
- CHANGELOG v0.3.4: 
- llvm-dis fails to disassemble bitcode file generated by Solang for a smart contract: https://github.com/hyperledger-solang/solang/issues/641
- Error in sema parsing contract: https://github.com/hyperledger-solang/solang/issues/731
- Solang loads vectors from storage incorrectly: https://github.com/hyperledger-solang/solang/issues/933
- 🚀 Use Borsh encoding everywhere on Solana ⚓: https://github.com/hyperledger-solang/solang/pull/1053
- Use named enums for a few cfg expressions: https://github.com/hyperledger-solang/solang/pull/1214

Human semantic review and a current open+closed upstream search are required before counting this as a new bug.
