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
```

## Routine

1. Enter the Nix shell with `nix develop`.
2. Generate deterministic Solidity seeds with `python3 ./working/scripts/generate_seeds.py`.
3. Compare `solc` and `solang` with `nu ./working/scripts/compare-compile.nu`.
4. Summarize mismatches with `python3 ./working/scripts/classify_mismatches.py`.
5. Copy interesting cases into `working/repro/` and minimize them.

## Scripts

- `working/scripts/generate_seeds.py`: creates a batch of small Solidity seeds in `working/cases/generated/`.
- `working/scripts/compare-compile.nu`: runs both compilers on every `working/cases/**/*.sol` input and stores results in `working/out/`.
- `working/scripts/classify_mismatches.py`: reads `working/out/` and prints a short mismatch summary.

## Important Directories

- `working/cases/`: hand-written and generated Solidity inputs
- `working/cases/generated/`: generated seed corpus
- `working/out/`: raw compiler outputs, statuses, and diffs
- `working/repro/`: minimized reproductions worth keeping
- `working/scripts/`: helper scripts for generation and comparison

## Notes

- `solang` is wrapped in the flake for `x86_64-linux`, so `nix develop` provides both compilers.
- Generated Solidity seeds include comments so each case is easier to inspect and reduce.
- The current workflow focuses on compile-time differences first because they are faster to discover and minimize.

See `working/README.md` for the workspace-specific layout.
