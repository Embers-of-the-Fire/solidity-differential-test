"""Frozen campaign provenance for reproducible discovery and evaluation runs."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import subprocess
import time
from importlib.resources import files
from pathlib import Path
from typing import Any

from .config import AgentConfig

ROOT = Path(__file__).resolve().parents[3]


def _run_version(command: list[str]) -> str:
    try:
        out = subprocess.run(
            command, capture_output=True, text=True, cwd=ROOT, timeout=30, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"unavailable: {type(e).__name__}"
    text = (out.stdout or out.stderr).strip()
    if out.returncode != 0:
        return f"exit {out.returncode}: {text[-500:]}"
    return text


def _json_value(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(v) for v in value]
    return value


def _config_record(cfg: AgentConfig) -> dict[str, Any]:
    record = _json_value(dataclasses.asdict(cfg))
    record.pop("api_key", None)
    return record


def _seed_hashes(seeds_dir: Path | None) -> dict[str, str]:
    if seeds_dir is None:
        seed_paths = [
            Path(str(files("agent") / "seeds" / name))
            for name in sorted(
                str(p.name) for p in (files("agent") / "seeds").iterdir()
            )
            if name.endswith(".json")
        ]
    else:
        seed_paths = sorted(seeds_dir.glob("*.json"))
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in seed_paths
    }


def _git_rev() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            cwd=ROOT,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    return out.stdout.strip() if out.returncode == 0 else "unknown"


def _upstream_corpus_date() -> str | None:
    path = ROOT / "agent" / "data" / "bug_corpus" / "raw" / "meta.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text()).get("fetched_at")
    except (OSError, json.JSONDecodeError):
        return None


def write_campaign_metadata(
    root: str | Path, cfg: AgentConfig, *, extra: dict[str, Any] | None = None
) -> Path:
    """Write campaign.json once; resuming a hunt preserves its original record."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    path = root / "campaign.json"
    if path.exists():
        return path
    record = {
        "schema_version": 1,
        "git_rev": _git_rev(),
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "config": _config_record(cfg),
        "seed_files_sha256": _seed_hashes(cfg.seeds_dir),
        "tool_versions": {
            "solc": _run_version(["solc", "--version"]),
            "solang": _run_version(
                [os.environ.get("ORACLE_SOLANG_BIN", "solang"), "--version"]
            ),
            "anvil": _run_version(["anvil", "--version"]),
            "substrate-contracts-node": _run_version(
                ["substrate-contracts-node", "--version"]
            ),
        },
        "upstream_corpus_fetched_at": _upstream_corpus_date(),
    }
    if extra:
        record.update(_json_value(extra))
    path.write_text(json.dumps(record, indent=2) + "\n")
    return path
