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
nu ./working/scripts/compare-compile.nu
```

The script writes normalized outputs into `working/out/` and prints unified diffs when it detects a mismatch.

`solang` is provided by the flake as a wrapped release binary for `x86_64-linux`, so `nix develop` makes both compilers available without a separate bootstrap step.

## Notes

- Solidity samples should include comments explaining the intent of the test.
- Start by collecting compile-time mismatches; add runtime harnesses under `scripts/` and `repro/` as cases mature.
