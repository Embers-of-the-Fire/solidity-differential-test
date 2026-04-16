# Solidity Differential Test

This repository is a small workspace for finding behavioral differences between `solc` and `solang`.

The environment is provided by `flake.nix`, and all generated work lives under `working/`.

## Quick Start

From the repository root:

```bash
nix develop
python3 ./working/scripts/generate_seeds.py
nu ./working/scripts/compare-compile.nu
python3 ./working/scripts/classify_mismatches.py
python3 ./working/scripts/run_issue_variants.py
```

## Routine

1. Enter the Nix shell with `nix develop`.
2. Generate deterministic Solidity seeds with `python3 ./working/scripts/generate_seeds.py`.
3. Compare `solc` and `solang` with `nu ./working/scripts/compare-compile.nu`.
4. Summarize candidate bugs with `python3 ./working/scripts/classify_mismatches.py`.
5. Probe nearby variants of known open Solang bugs with `python3 ./working/scripts/run_issue_variants.py`.
6. Copy interesting cases into `working/repro/` and minimize them.

## Scripts

- `working/scripts/generate_seeds.py`: creates a batch of small Solidity seeds in `working/cases/generated/` that are intended to compile on both compilers and stress likely semantic/codegen edges.
- `working/scripts/compare-compile.nu`: runs both compilers on every `working/cases/**/*.sol` input and stores results in `working/out/`.
- `working/scripts/classify_mismatches.py`: reads `working/out/`, strips ANSI escape sequences, filters documented Solana-target unsupported-feature noise, and prints only internal compiler failures or shared-success acceptance mismatches.
- `working/scripts/run_issue_variants.py`: compiles targeted repro variants derived from open Solang issues and prints whether each one still panics, succeeds, or only emits a normal diagnostic.

## Important Directories

- `working/cases/`: hand-written and generated Solidity inputs
- `working/cases/generated/`: generated seed corpus
- `working/out/`: raw compiler outputs, statuses, and diffs
- `working/repro/`: minimized reproductions worth keeping
- `working/cases/issue_variants/`: hand-written nearby variants of current upstream Solang bug reports, included automatically by `compare-compile.nu`
- `working/scripts/`: helper scripts for generation and comparison

## Notes

- `solang` is wrapped in the flake for `x86_64-linux`, so `nix develop` provides both compilers.
- Generated Solidity seeds include comments so each case is easier to inspect and reduce.
- The generated corpus intentionally avoids obvious expected rejections. The goal is to surface internal compiler failures or cases that should compile on both compilers but do not.

See `working/README.md` for the workspace-specific layout.
