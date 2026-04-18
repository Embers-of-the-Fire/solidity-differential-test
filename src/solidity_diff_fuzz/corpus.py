from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from .models import MismatchKind, MismatchRecord


def ensure_directories(paths: list[Path]) -> None:
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)


def source_digest(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def load_existing_source_digests(queue_dir: Path) -> set[str]:
    if not queue_dir.exists():
        return set()
    return {
        source_digest(path.read_text(encoding="utf-8"))
        for path in queue_dir.glob("*.sol")
        if path.is_file()
    }


def load_known_signatures(*directories: Path) -> set[str]:
    signatures: set[str] = set()
    for directory in directories:
        if not directory.exists():
            continue
        for path in directory.glob("*.json"):
            if not path.is_file():
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            signature = payload.get("signature")
            if isinstance(signature, str):
                signatures.add(signature)
    return signatures


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
