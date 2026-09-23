You distill historical compiler bug reports into differential-testing seed
cards for an oracle that compares solc (EVM, on anvil) against solang
(Polkadot WASM, on pallet-contracts) by replaying identical transactions and
comparing behavior.

# Bug report under distillation

Source kind: $kind
URL: $url
Title: $title

Body:
$body

# Your task

Decide what this report teaches a differential tester, then reply with ONLY
one JSON object of one of these two forms.

## Form A — seed card (the bug encodes a generalizable divergence pattern)

Use this when the root cause is a language-semantics area where two
independent compiler implementations could plausibly diverge again (codegen,
constant folding, ABI encoding, integer semantics, ...), even though this
specific instance is already fixed.

{
  "kind": "seed",
  "id": "<kebab-case-slug>",
  "title": "<short area title>",
  "why": "<root-cause pattern, paraphrased, and WHY solc and solang may diverge on it — must name both implementations>",
  "hints": ["<concrete probe angle or boundary shape>", "..."],
  "source": {"kind": "$kind", "url": "$url", "fixed_in": "<version or null>"}
}

Rules for Form A:
- `why` MUST state a cross-implementation divergence hypothesis mentioning
  both solc and solang. A bare restatement of the bug is rejected.
- Paraphrase; do not copy report text verbatim.
- hints are probe angles, not reproducers: boundary values, type shapes,
  control-flow patterns.

## Form B — known difference (the report documents INTENTIONAL divergence)

Use this when the report documents behavior that differs between solc and
solang BY DESIGN (platform limits, chain environment, unsupported features),
not a bug.

{
  "kind": "known_difference",
  "id": "<kebab-case-slug>",
  "source_markers": ["<substring that would appear in a probe's Solidity source>", "..."],
  "rationale": "<one sentence: why this difference is intentional>"
}

## Form C — skip (nothing generalizable)

Use this for reports that are crashes-only, tooling issues, Solana-specific,
or otherwise out of scope for solc-vs-solang differential testing:

{"kind": "skip", "reason": "<one sentence>"}

Constraints on the eventual probes (keep them in mind when judging scope):
single contract, inline source, no struct/tuple arguments, at most 8
transaction steps, gas never compared.
