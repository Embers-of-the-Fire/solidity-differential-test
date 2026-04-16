#!/usr/bin/env python3

from __future__ import annotations

import json
from pathlib import Path
import re


ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
TARGET_NOISE_PATTERNS = (
    "not supported on solana",
    "target solana does not support",
)
INTERNAL_ERROR_PATTERNS = (
    "internal compiler error",
    "panic",
    "assertion failed",
    "unreachable",
    "stack backtrace",
    "thread '",
    "segmentation fault",
)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def normalize_stderr(text: str) -> str:
    normalized = ANSI_ESCAPE.sub("", text)
    return "\n".join(line.rstrip() for line in normalized.splitlines()).strip()


def is_target_noise(text: str) -> bool:
    lowered = normalize_stderr(text).lower()
    return any(pattern in lowered for pattern in TARGET_NOISE_PATTERNS)


def is_internal_error(text: str) -> bool:
    lowered = normalize_stderr(text).lower()
    return any(pattern in lowered for pattern in INTERNAL_ERROR_PATTERNS)


def load_manifest(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}

    raw_entries = json.loads(path.read_text(encoding="utf-8"))
    return {entry["name"]: entry for entry in raw_entries}


def classify_case(
    case_dir: Path, manifest_entry: dict[str, str] | None
) -> tuple[str, str] | None:
    solc_status = read_text(case_dir / "solc.status").strip()
    solang_status = read_text(case_dir / "solang.status").strip()
    solc_stderr = normalize_stderr(read_text(case_dir / "solc.stderr"))
    solang_stderr = normalize_stderr(read_text(case_dir / "solang.stderr"))

    if not solc_status and not solang_status:
        return None

    if is_internal_error(solang_stderr):
        return ("internal-error", "solang reported an internal compiler failure")

    if is_internal_error(solc_stderr):
        return ("internal-error", "solc reported an internal compiler failure")

    if solc_status != solang_status:
        if is_target_noise(solang_stderr):
            return None

        if manifest_entry and manifest_entry.get("expectation") == "shared-success":
            if solc_status == "success":
                return (
                    "candidate",
                    "solc accepted a shared-success case but solang rejected it",
                )
            return (
                "candidate",
                "solang accepted a shared-success case but solc rejected it",
            )

    return None


def main() -> None:
    root_dir = Path(__file__).resolve().parents[2]
    cases_dir = root_dir / "working" / "cases"
    out_dir = root_dir / "working" / "out"
    current_cases = {path.stem for path in cases_dir.rglob("*.sol")}
    manifest = load_manifest(cases_dir / "generated" / "manifest.json")

    mismatches: list[tuple[str, str, str]] = []
    for case_dir in sorted(path for path in out_dir.iterdir() if path.is_dir()):
        if case_dir.name not in current_cases:
            continue

        classified = classify_case(case_dir, manifest.get(case_dir.name))
        if classified is None:
            continue

        kind, summary = classified
        mismatches.append((case_dir.name, kind, summary))

    if not mismatches:
        print(
            "No internal-error or shared-success acceptance mismatches recorded in working/out"
        )
        return

    for case_name, kind, summary in mismatches:
        print(f"{case_name}: {kind}: {summary}")


if __name__ == "__main__":
    main()
