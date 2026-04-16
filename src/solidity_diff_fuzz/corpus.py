from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .models import MismatchKind, MismatchRecord


def ensure_directories(paths: list[Path]) -> None:
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)


def persist_mismatch(
    record: MismatchRecord, interesting_dir: Path, crashes_dir: Path
) -> Path:
    destination_dir = (
        crashes_dir if record.kind == MismatchKind.CRASH else interesting_dir
    )
    destination_dir.mkdir(parents=True, exist_ok=True)
    path = destination_dir / f"{record.case_id}.{record.signature}.json"
    path.write_text(
        json.dumps(asdict(record), indent=2, sort_keys=True), encoding="utf-8"
    )
    return path
