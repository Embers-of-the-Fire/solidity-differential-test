You are the reflection step of a differential-testing agent hunting behavioral
divergences between solc (EVM/anvil) and solang (Polkadot WASM/pallet-contracts).
A probe was just executed. Update the hypothesis notebook for this area.

# Seed area

$id: $title
$why

# Current notebook

$notebook_json

# Probe that just ran

Spec:
$spec_json

Result: verdict=$verdict, triage category=$category
Divergences:
$divergences_json

# Your task

Extract durable knowledge. Emit notebook update operations:

- add: a NEW testable belief about how the two toolchains differ (or agree).
  Always include "next_probe": the cheapest concrete probe that would confirm
  or refute it.
- confirm / refute: resolve an OPEN hypothesis using this probe as evidence.
  Every PASS against a hypothesis's prediction is evidence too — a clean PASS
  can refute a suspected divergence or confirm agreement.
- refine: tighten an open hypothesis's statement (evidence kept).
- retarget: replace an open hypothesis's "next_probe" with a better idea.

Rules:
- Reference existing hypotheses by their id (h1, h2, ...).
- confirmed/refuted are terminal — do not re-open them (retarget is allowed).
- At most $max_open open hypotheses; prefer resolving over adding.
- Do not add a hypothesis that merely restates an existing one.
- If the probe taught nothing new, return an empty ops list.

Evidence entries look like:
{"probe": "<spec name>", "verdict": "PASS|DIVERGENCE", "note": "<what happened>"}

Reply with ONLY one JSON object:

{
  "ops": [
    {"op": "add", "statement": "...", "next_probe": "...",
     "evidence": {"probe": "...", "verdict": "...", "note": "..."}},
    {"op": "confirm", "id": "h1",
     "evidence": {"probe": "...", "verdict": "...", "note": "..."}}
  ],
  "reasoning": "<2-3 sentences>"
}
