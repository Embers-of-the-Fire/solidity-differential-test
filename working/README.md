# Working Directory

This directory stores all code-side work for differential testing between `solc` and `solang`.

## Layout

- `cases/`: Solidity inputs to compare across compilers
- `out/`: compiler outputs and diffs
- `repro/`: minimized reproductions for interesting mismatches
- `scripts/`: helper scripts used from inside the Nix shell

## Usage

Enter the development shell from the repository root:

```bash
nix develop
```

Then run the compile comparison harness:

```bash
python3 ./working/scripts/generate_seeds.py
nu ./working/scripts/compare-compile.nu
python3 ./working/scripts/classify_mismatches.py
```

The script writes normalized outputs into `working/out/` and prints unified diffs when it detects a mismatch.

`solang` is provided by the flake as a wrapped release binary for `x86_64-linux`, so `nix develop` makes both compilers available without a separate bootstrap step.

## Notes

- Solidity samples should include comments explaining the intent of the test.
- Start by collecting compile-time mismatches; add runtime harnesses under `scripts/` and `repro/` as cases mature.
- Generated seeds are written to `working/cases/generated/` so hand-written repros can stay in `working/cases/`.
- The generator is deterministic, which makes it easier to bisect and minimize compiler disagreements.
