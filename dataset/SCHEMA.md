# Witness dataset schema

One directory per witness under `witnesses/<id>/`:

- `spec.orig.json` — spec as discovered (pre-reduction). Legacy findings
  (pre-L1 pipeline) store the reduced spec here too; `provenance.json`
  marks them `"legacy": true`.
- `spec.min.json` — the reduced witness spec (oracle test-environment
  schema; see `oracle/README.md`).
- `report.min.json` — the oracle report produced by replaying
  `spec.min.json` at export time.
- `signature.json` — witness identity: `fingerprint` (sha1 over the sorted
  divergence-signature set), `earliest_signature`, full `signatures` list.
  Signature format: `<kind>|<point>|<function-or-empty>|<relation>`; see
  `oracle/src/oracle/signature.py`.
- `provenance.json` — compiler/node versions at export, repo git revision,
  export timestamp.

Verification: `uv run python dataset/verify_all.py` replays every
`spec.min.json` through the oracle and asserts the earliest signature
matches `signature.json` (exit 1 on any mismatch).
