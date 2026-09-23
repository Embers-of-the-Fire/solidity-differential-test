"""Oracle executor: run spec dicts through the oracle, in-process.

Specs arrive as plain dicts (LLM output). They are serialized to a temp file
so the oracle's own `load_test_spec` remains the single source of validation,
then executed via `oracle.runner.run_spec`. The oracle is designed to record
unexpected behavior as data rather than crash, but we still guard every call
so a rogue node/compiler state never kills the hunt loop.
"""

from __future__ import annotations

import json
import tempfile
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Protocol

from oracle.runner import run_spec
from oracle.spec import load_test_spec


class OracleRunner(Protocol):
    """Structural type for anything the loop can query as an oracle."""

    runs: int

    def run(self, spec_dict: dict[str, Any]) -> dict[str, Any]: ...

    def run_many(self, spec_dicts: list[dict[str, Any]]) -> list[dict[str, Any]]: ...

    def close(self) -> None: ...


def run_spec_dict(
    spec_dict: dict[str, Any],
    workdir: str | Path | None = None,
    verbose: bool = False,
) -> dict[str, Any]:
    """Run one spec dict through the oracle; return the report dict.

    Never raises: failures become a report with verdict "ERROR".
    """
    try:
        tmpdir = Path(tempfile.mkdtemp(prefix="agent-spec-"))
        spec_path = tmpdir / "spec.json"
        spec_path.write_text(json.dumps(spec_dict))
        spec = load_test_spec(spec_path)
        return run_spec(spec, workdir=workdir, verbose=verbose)
    except Exception as e:  # noqa: BLE001 - the loop must survive anything
        return {
            "name": spec_dict.get("name", "<unnamed>"),
            "verdict": "ERROR",
            "divergences": [],
            "error": f"{type(e).__name__}: {e}",
            "traceback": traceback.format_exc(),
        }


def divergence_kinds(report: dict[str, Any]) -> set[str]:
    return {d["kind"] for d in report.get("divergences", [])}


class Executor:
    """Parallel oracle runner. Nodes pick free ports and use --tmp chains,
    so concurrent runs are safe (each run still pays node startup)."""

    def __init__(self, parallel: int = 4, verbose: bool = False):
        self.verbose = verbose
        self.runs = 0
        self._pool = ThreadPoolExecutor(max_workers=max(1, parallel))

    def run(self, spec_dict: dict[str, Any]) -> dict[str, Any]:
        self.runs += 1
        return run_spec_dict(spec_dict, verbose=self.verbose)

    def run_many(self, spec_dicts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        self.runs += len(spec_dicts)
        return list(
            self._pool.map(lambda s: run_spec_dict(s, verbose=self.verbose), spec_dicts)
        )

    def close(self) -> None:
        self._pool.shutdown(wait=True)
