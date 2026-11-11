# Review probe-2c1aa1c41d764ef6b7a19fec3fec9981

Status: **survivor**; origin: `rejected_probe`

## Minimized/current spec

```solidity
pragma solidity >=0.8.0;

contract CryptoHashStaticNonInt {
    bytes32 public packedKeccak;
    bytes32 public encodedKeccak;
    bytes32 public packedSha;
    bytes32 public encodedSha;

    event Hash(bytes32 packedKeccak, bytes32 encodedKeccak, bytes32 packedSha, bytes32 encodedSha);

    function set(address a, bool b, bytes4 c) public {
        packedKeccak = keccak256(abi.encodePacked(a, b, c));
        encodedKeccak = keccak256(abi.encode(a, b, c));
        packedSha = sha256(abi.encodePacked(a, b, c));
        encodedSha = sha256(abi.encode(a, b, c));
        emit Hash(packedKeccak, encodedKeccak, packedSha, encodedSha);
    }

    function getPackedKeccak() public view returns (bytes32) { return packedKeccak; }
    function getEncodedKeccak() public view returns (bytes32) { return encodedKeccak; }
    function getPackedSha() public view returns (bytes32) { return packedSha; }
    function getEncodedSha() public view returns (bytes32) { return encodedSha; }
}
```

## Earliest divergence

```json
{
  "point": 0,
  "signature": "EVENT_MISMATCH|0|set|args"
}
```

## Panel

```json
[
  {
    "category": "bug_candidate",
    "confidence": "high",
    "evidence": "On both set() calls (steps 0 and 1), solang/Polkadot emits packedKeccak == encodedKeccak (0x6a70c1.../0x6a70c1... and 0xe0dc77.../0xe0dc77...) and packedSha == encodedSha (0xadd6bc.../0xadd6bc... and 0x1f72da.../0x1f72da...), whereas EVM/solc produces four distinct hashes (e.g. step 1: packedKeccak=0x383ec8..., encodedKeccak=0x5492cb..., packedSha=0x627a0f..., encodedSha=0x148466...). The pattern is systematic across two different argument sets, ruling out hash collision. Return queries (steps 2-5) confirm solang's stored values pair-wise equal while solc's differ.",
    "rationale": "abi.encodePacked(address,bool,bytes4) should yield 37 unpadded bytes while abi.encode yields 96 padded bytes, so the four hashes must differ on both chains. Solang producing identical hashes for the packed and encoded variants at both steps indicates it is not applying the pack-vs-pad distinction (e.g., encodePacked padding like encode, or encode not padding), a real semantic defect rather than an environment or oracle artifact. The negative storage values in count mode are a signed-cell projection artifact, but the event args and query return values are exact bytes32 comparisons and are unambiguous.",
    "historical_match_url": "",
    "cluster_hint": "solang computes abi.encodePacked identical to abi.encode for static non-integer types (address/bool/bytes4), i.e., packing vs padding distinction lost"
  },
  {
    "category": "bug_candidate",
    "confidence": "high",
    "evidence": "At step 0, EVM emits distinct packedKeccak=0x3e9fd8ed... and encodedKeccak=0x4ff19c63... (and distinct sha256 pair), while solang emits packedKeccak==encodedKeccak=0x6a70c173... and packedSha==encodedSha=0xadd6bce1.... The same collision repeats at step 1 with different args ($bob,false,0x00000000), and the subsequent query returns confirm solang's stored state: getPackedKeccak and getEncodedKeccak both return 0xe0dc776e..., getPackedSha and getEncodedSha both return 0x1f72da2d.... abi.encodePacked(address,bool,bytes4) is a 25-byte concatenation while abi.encode pads each argument to 32 bytes (96 bytes), so the two hashes cannot legitimately be equal for any conforming implementation; solc's four distinct values are the reference behavior.",
    "rationale": "The divergence is internally consistent across events, storage, and return-value projections, so it is not an oracle artifact of storage-count mode or event decoding. The inputs (address, bool, bytes4) are static non-integer types whose packed (1-byte bool, unpadded address/bytes4) and encoded (32-byte padded) forms differ, yet solang produces identical digests for both operations in two independent calls. This indicates solang is collapsing abi.encodePacked and abi.encode for these argument types (not applying tight packing, or padding both), a real semantic defect rather than an intentional chain difference. No documented known-difference category covers hashing/ABI encoding, and no supplied historical record matches this root cause.",
    "historical_match_url": "",
    "cluster_hint": "solang abi.encodePacked equals abi.encode for mixed static non-integer args (address, bool, bytes4): tight packing not applied, so both hashes collide"
  }
]
```

## Adversarial review

```json
{
  "rebuttal_succeeds": false,
  "category": "bug_candidate",
  "evidence": "At both set() calls solang returns identical digests for abi.encodePacked(a,b,c) and abi.encode(a,b,c): step 0 packedKeccak==encodedKeccak==0x6a70c173... and packedSha==encodedSha==0xadd6bce1...; step 1 packedKeccak==encodedKeccak==0xe0dc776e... and packedSha==encodedSha==0x1f72da2d.... The independent query steps 2-5 read the contract state back and reproduce exactly these pair-wise equal values, so the equality is in solang's computed storage, not in event decoding. abi.encodePacked(address,bool,bytes4) is a 25-byte tight concatenation while abi.encode pads each argument to 32 bytes (96 bytes total); for a conforming implementation the four digests cannot collapse into two, and observing the collapse simultaneously in both keccak256 and sha256 across two distinct argument sets rules out collision probability. Negative storage-count entries are a signed-projection artifact, but the bytes32 event args and dry-run return values are exact hex comparisons.",
  "rationale": "The only plausible explanations are (a) solang emits identical bytes for encodePacked and encode for these static non-integer types, or (b) the oracle mislabeled which value went where \u2014 but (b) is excluded because the storage-write events and the independent view-function queries independently confirm the pair-wise equality in solang state. This is core ABI-encoding semantics that Solang must match for EVM compatibility, not an environment value (no gasleft/block/tx markers), not gas metering, and not covered by any documented known difference. The solc side produces four distinct, spec-conformant digests, so this is not a solc defect either. None of the supplied historical records concern abi.encodePacked packing semantics, so it is not a demonstrated rediscovery. The evidence survives scrutiny.",
  "historical_match_url": ""
}
```

## Potentially relevant historical records

- thread 'main' panicked while compiling BlindAuction from Solidity official website: https://github.com/hyperledger-solang/solang/issues/1076
- llvm-dis fails to disassemble bitcode file generated by Solang for a smart contract: https://github.com/hyperledger-solang/solang/issues/641
- LLVM crashes when building contract: https://github.com/hyperledger-solang/solang/issues/776
- a.b.selector adds b() as function to current contract: https://github.com/hyperledger-solang/solang/pull/1462
- Scratch buffer data leakages : https://github.com/hyperledger-solang/solang/issues/1399
- Accessing function selectors adds foreign contracts functions: https://github.com/hyperledger-solang/solang/issues/1461
- Reserved keywords collision in Yul assembly: https://github.com/hyperledger-solang/solang/issues/639
- Error in sema parsing contract: https://github.com/hyperledger-solang/solang/issues/731

Human semantic review and a current open+closed upstream search are required before counting this as a new bug.
