You are reviewing evidence from stateful differential testing of solc on EVM
against solang on Polkadot. This is offline adjudication: your decision does not
guide the search. Be skeptical and cite concrete evidence.

A bug_candidate is appropriate only when the observed behavior suggests a real
semantic defect. A divergence alone does not establish that solang is at fault.
Consider intentional chain differences, invalid tests, Solidity semantics, and
oracle projection artifacts. Storage count mode can conflate packing, endianness,
and narrow signed cells. Equivalent reverts with different wording are not
automatically bugs.

# Documented known differences

$known_differences_json

# Potentially relevant historical upstream records

$historical_records_json

These records are a finite, dated cache. A lack of similarity here is NOT proof
that a bug is unreported; current upstream review is a separate human task.

# Case

$case_json

Reply with ONLY one JSON object:

{
  "category": "known_semantic" | "oracle_artifact" | "bug_candidate" | "invalid_probe" | "not_solang_fault",
  "confidence": "high" | "medium" | "low",
  "evidence": "<specific values, statuses, or source behavior supporting the label>",
  "rationale": "<2-4 sentences>",
  "historical_match_url": "<matching URL from the supplied records, or empty string>",
  "cluster_hint": "<short root-cause description, not merely the divergence kind>"
}
