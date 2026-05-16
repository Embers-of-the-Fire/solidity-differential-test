# AGENTS.md

## Environment

- Use `nix develop` before running compiler harnesses; the flake provides `solc`, wrapped `solang` 0.3.4, `nushell`, `ruff`, `pytest`, and Nix linters.
- Do not assume `solang` exists outside the dev shell; scripts intentionally fail with “Enter the shell with `nix develop`” when tools are missing.
- Use `uv` for the Python package workflow because `uv.lock` is present and README commands use `uv`; do not introduce npm/pnpm tooling.

## Where to Put Work

- Put new generated Solidity seeds under `working/cases/generated/` by updating `working/scripts/generate_seeds.py`; do not hand-edit generated seed files as source of truth.
- Put hand-written nearby variants of known Solang issues under `working/cases/issue_variants/`; `compare-compile.nu` includes every `working/cases/**/*.sol` automatically.
- Put minimized, durable compiler repros under root `repros/`, not `working/repro/`; the tracked repro README documents the current crash families there.
- Put Python fuzzer logic under `src/solidity_diff_fuzz/` and its Solidity snippets under `templates/`; rendered campaign artifacts belong under `artifacts/`.
- Put research/planning notes under `workspace/` in a topic-specific subfolder instead of expanding existing pre-research notes unless asked.

## Core Commands

- Deterministic harness flow: `python3 ./working/scripts/generate_seeds.py`, then `nu ./working/scripts/compare-compile.nu`, then `python3 ./working/scripts/classify_mismatches.py`.
- Issue-neighborhood probe: `python3 ./working/scripts/run_issue_variants.py`.
- Python fuzzer setup and smoke run: `uv sync`, then `uv run solidity-diff-fuzz generate --seed 0 --case-index 0`, then `uv run solidity-diff-fuzz campaign --iterations 10 --mutate-rounds 2`.
- Run all tests: `uv run pytest`.
- Run one test file or case: `uv run pytest tests/test_oracle.py` or `uv run pytest tests/test_oracle.py::test_crash_signature_captures_message`.
- Format and lint Python after changes: `nix develop -c ruff format .` then `nix develop -c ruff check .`.
- Format/lint Nix after flake edits: `nix develop -c nixfmt flake.nix` then `nix develop -c statix check flake.nix`.

## Harness Gotchas

- `working/scripts/compare-compile.nu` compares `solc --abi --bin` against `solang compile --target solana`; the Python fuzzer defaults to `solang --target evm`.
- The Python oracle treats crashes, acceptance mismatches, and diagnostic-class mismatches as interesting, and ignores `unsupported` gaps.
- `working/scripts/classify_mismatches.py` filters documented Solana-target unsupported-feature noise, so do not treat every Solana rejection as a candidate bug.
- Generated seeds are intended to be shared-success, small, and comment-explained; avoid adding obvious expected rejections to the main generated corpus.

## Known Check State

- `ruff check .` currently reports pre-existing import-order and line-length issues in `working/scripts/classify_mismatches.py` and `working/scripts/generate_seeds.py`; do not conflate those with unrelated Markdown or research-note edits.
