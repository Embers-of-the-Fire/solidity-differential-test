#!/usr/bin/env python3

from __future__ import annotations

from pathlib import Path


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def classify_case(case_dir: Path) -> tuple[str, str] | None:
    solc_status = read_text(case_dir / "solc.status").strip()
    solang_status = read_text(case_dir / "solang.status").strip()
    solc_stderr = read_text(case_dir / "solc.stderr").strip()
    solang_stderr = read_text(case_dir / "solang.stderr").strip()

    if not solc_status and not solang_status:
        return None

    if solc_status != solang_status:
        if solc_status == "success":
            return ("acceptance", "solc accepted but solang rejected")
        return ("acceptance", "solang accepted but solc rejected")

    if solc_stderr != solang_stderr:
        return ("diagnostic", "both produced different diagnostics")

    return None


def main() -> None:
    root_dir = Path(__file__).resolve().parents[2]
    out_dir = root_dir / "working" / "out"

    mismatches: list[tuple[str, str, str]] = []
    for case_dir in sorted(path for path in out_dir.iterdir() if path.is_dir()):
        classified = classify_case(case_dir)
        if classified is None:
            continue

        kind, summary = classified
        mismatches.append((case_dir.name, kind, summary))

    if not mismatches:
        print("No compile-time mismatches recorded in working/out")
        return

    for case_name, kind, summary in mismatches:
        print(f"{case_name}: {kind}: {summary}")


if __name__ == "__main__":
    main()
