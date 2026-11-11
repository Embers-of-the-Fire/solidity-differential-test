# Review finding-094d66a5e0aec002

Status: **survivor**; origin: `finding`

## Minimized/current spec

```solidity
pragma solidity >=0.8.0;

contract CryptoHashPackedStatic {
    bytes32 public packedKeccak;
    bytes32 public encodedKeccak;
    bytes32 public packedSha;
    bytes32 public encodedSha;
    bytes20 public packedRipemd;
    bytes20 public encodedRipemd;

    event Hash32(bytes32 packedKeccak, bytes32 encodedKeccak, bytes32 packedSha, bytes32 encodedSha);
    event HashRipemd(bytes20 packedRipemd, bytes20 encodedRipemd);

    function set(uint8 a, uint16 b, uint64 c, uint256 d) public {
        packedKeccak = keccak256(abi.encodePacked(a, b, c, d));
        encodedKeccak = keccak256(abi.encode(a, b, c, d));
        packedSha = sha256(abi.encodePacked(a, b, c, d));
        encodedSha = sha256(abi.encode(a, b, c, d));
        packedRipemd = ripemd160(abi.encodePacked(a, b, c, d));
        encodedRipemd = ripemd160(abi.encode(a, b, c, d));
        emit Hash32(packedKeccak, encodedKeccak, packedSha, encodedSha);
        emit HashRipemd(packedRipemd, encodedRipemd);
    }

    
    
    
    
    
    
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
    "evidence": "On EVM, packedKeccak=0xdafb08ad...f2f85c differs from encodedKeccak=0x01289365...fc8e3d (43 zero bytes vs 128 zero bytes of ABI padding), as Solidity semantics require. On Polkadot, encodedKeccak == packedKeccak (0xdafb08ad...), encodedSha == packedSha, encodedRipemd == packedRipemd \u2014 solang is hashing the packed encoding for abi.encode. The storage multiset confirms it: the four bytes32/bytes20 slots on EVM hold 4 distinct hash values, while Polkadot's 6 nonzero entries contain each value exactly twice (e.g., -1674434974...712108 appears twice, 1240155221...6773 twice), i.e., packedX and encodedX variables hold identical values.",
    "rationale": "The test is valid Solidity: abi.encode of static uint types must pad each argument to 32 bytes, yielding a different pre-image than encodePacked. The divergence is a precise, semantics-violating hash difference (not wording, gas, env values, or storage-count projection artifacts), and it is internally consistent across events and storage, ruling out an oracle projection bug. The historical records concern compiler panics/inkwell crashes, scratch-buffer leakage, and 'now' errors \u2014 none match this abi.encode codegen defect. This points to a real solang bug where abi.encode for static arguments is emitted as packed encoding.",
    "historical_match_url": "",
    "cluster_hint": "solang abi.encode for static uint arguments collapses to encodePacked (missing 32-byte padding), making encoded and packed hashes identical"
  },
  {
    "category": "bug_candidate",
    "confidence": "high",
    "evidence": "On Polkadot, encodedKeccak == packedKeccak == 0xdafb08ad...f85c, encodedSha == packedSha == 0x859732b9...14f2, and encodedRipemd == packedRipemd == 0xd93a7bc1...6a05, whereas solc/EVM yields distinct encoded hashes (encodedKeccak=0x01289365...8e3d). The storage multiset independently corroborates this: Polkadot contains each hash value duplicated (e.g., the dafb08ad... preimage appears twice, as does 859732b9...), i.e., the packed hash was stored in both the packedKeccak and encodedKeccak slots. abi.encode(uint8,uint16,uint64,uint256) must left-pad each argument to 32 bytes (128 bytes total), while abi.encodePacked yields 43 bytes, so the two hashes can never be equal.",
    "rationale": "The divergence is not a known chain difference (no env-value or gas markers) and not an oracle projection artifact: the event args and the raw storage value multiset agree, ruling out the storage-count conflation caveat. Solang appears to compile abi.encode of these static integer types into packed (unpadded) encoding, collapsing distinct Solidity-semantics hashes \u2014 a real semantic codegen defect rather than an intentional difference. A revert-rewording or invalid-probe explanation does not apply since both chains executed successfully and the test is valid Solidity.",
    "historical_match_url": "",
    "cluster_hint": "solang emits unpadded/packed encoding for abi.encode of static integer types, making encode and encodePacked hashes identical"
  }
]
```

## Adversarial review

```json
{
  "rebuttal_succeeds": false,
  "category": "bug_candidate",
  "evidence": "The divergence is not explained by environment values, gas, revert wording, or storage-count projection: for set(0,0,0,0), EVM gives packedKeccak=0xdafb08ad...f2f85c but encodedKeccak=0x01289365...fc8e3d, while Polkadot reports encodedKeccak equal to packedKeccak=0xdafb08ad...f2f85c; the same collapse occurs for sha256 and ripemd160. The raw storage multiset independently corroborates this, with Polkadot containing duplicated hash values in the packed and encoded slots. Under the Solidity ABI, abi.encode(uint8,uint16,uint64,uint256) must left-pad each static argument to 32 bytes (128 bytes total), whereas abi.encodePacked concatenates 1+2+8+32=43 bytes, so equality of the encoded and packed hashes is semantically impossible for a correct implementation.",
  "rationale": "The strongest rebuttal would be that solc or the oracle miscompares abi.encode vs encodePacked, but the test is valid Solidity and the event values plus storage duplicates agree, so this is not an oracle projection artifact. It is not a documented anvil/pallet-contracts platform difference and has no matching historical record among the supplied panic/inkwell/scratch-buffer items. The observed behavior is consistent with solang emitting an unpadded/packed encoding for abi.encode of static integer arguments, a real semantic codegen defect.",
  "historical_match_url": ""
}
```

## Potentially relevant historical records

- thread 'main' panicked while compiling BlindAuction from Solidity official website: https://github.com/hyperledger-solang/solang/issues/1076
- LLVM crashes when building contract: https://github.com/hyperledger-solang/solang/issues/776
- Inkwell crashes when building for Solana and Substrate: https://github.com/hyperledger-solang/solang/issues/813
- Substrate: Implement builtin for `set_code_hash` API: https://github.com/hyperledger-solang/solang/pull/1397
- Thread 'main' panicked  error when compiling call with seeds: https://github.com/hyperledger-solang/solang/issues/1028
- Scratch buffer data leakages : https://github.com/hyperledger-solang/solang/issues/1399
- llvm-dis fails to disassemble bitcode file generated by Solang for a smart contract: https://github.com/hyperledger-solang/solang/issues/641
- Error message for "now" is wrong: https://github.com/hyperledger-solang/solang/issues/779

Human semantic review and a current open+closed upstream search are required before counting this as a new bug.
