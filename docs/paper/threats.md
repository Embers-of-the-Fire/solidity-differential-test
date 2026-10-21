# Threats to validity — DRAFT scaffold

- **Oracle projection loss.** π compares a storage *multiset* by default;
  slot-packing aliasing could hide real differences (count mode) or invent
  them (exact mode — measured: 2/5 exact-mode mismatches are spurious,
  `eval/rq1/storage_modes.json`). Return-value comparison normalizes
  serializations; exotic encodings may still alias.
- **Single chain pair.** anvil and substrate-contracts-node stand in for
  "EVM" and "Polkadot"; neither is a production client. solang 0.3.0 is
  incompatible with the current node (metadata decode) — matching-era node
  pinning is future work (`agent/data/version_matrix.json`).
- **Known-artifact suppressions** (compare.py) may over-suppress; each is
  documented and the raw values stay in the report.
- **Ground-truth set size.** 6 admitted bugs (`agent/data/ground_truth/`);
  rejected candidates are kept under `ground_truth/rejected/` with reasons.
  Rediscovery rates over 6 bugs are coarse-grained.
- **LLM variance.** Generation/triage/reflect depend on the model; mitigated
  by deterministic rng seeds, per-stage usage tracing, 5 repeats, and the
  deterministic reduction stack downstream (no LLM needed for L0/L1 results).
- **Determinism of the chains.** Checked by replay
  (`eval/rq5/determinism.json`; 3/3 stable on the current corpus).
- **Signature predicate.** Signature equality is stricter than human
  root-cause judgment in one direction (same bug, different first
  observable) and looser in another (distinct bugs sharing kind+point+
  relation); the T0.1 audit (`docs/agents/refine/notes/signature-audit.md`)
  found no mis-carving on the seed corpus, and the drift experiment
  (`docs/agents/refine/notes/drift-audit.md`) bounds the lenient
  alternative's failure mode.
