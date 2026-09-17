"""Findings store: append-only JSONL, fingerprint dedup.

Layout under the findings dir:

    probes.jsonl      every probe: spec, verdict, triage category, seed id
    findings.jsonl    accepted findings (bug candidates), one per line
    reports/<id>.json full oracle report for each finding
    seeds_state.json  per-seed coverage stats (probes run, kinds found)

Kept dependency-free (no SQLite): the volume is low and JSONL is greppable,
diff-able and trivially replayable.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from .executor import divergence_kinds


def fingerprint(divergence_kinds: set[str], detail: str, source: str) -> str:
    """Stable dedup key: kinds + normalized detail + source text."""
    norm_detail = " ".join(detail.lower().split())
    src = " ".join(source.split())
    h = hashlib.sha1()
    h.update("|".join(sorted(divergence_kinds)).encode())
    h.update(b"\x00")
    h.update(norm_detail.encode())
    h.update(b"\x00")
    h.update(src.encode())
    return h.hexdigest()[:16]


class FindingStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "reports").mkdir(exist_ok=True)
        self._probes = self.root / "probes.jsonl"
        self._findings = self.root / "findings.jsonl"
        self._seeds_state = self.root / "seeds_state.json"

    # --- probes -------------------------------------------------------------

    def record_probe(
        self,
        *,
        spec: dict[str, Any],
        report: dict[str, Any],
        seed_id: str,
        category: str,
    ) -> None:
        self._append(
            self._probes,
            {
                "ts": time.time(),
                "seed": seed_id,
                "name": spec.get("name"),
                "verdict": report.get("verdict"),
                "category": category,
                "kinds": sorted(divergence_kinds(report)),
            },
        )

    def recent_probes(self, n: int = 15) -> list[dict[str, Any]]:
        if not self._probes.exists():
            return []
        lines = self._probes.read_text().strip().splitlines()
        return [json.loads(line) for line in lines[-n:]]

    # --- findings -----------------------------------------------------------

    def known_fingerprints(self) -> set[str]:
        if not self._findings.exists():
            return set()
        return {
            json.loads(line)["fingerprint"]
            for line in self._findings.read_text().strip().splitlines()
        }

    def add_finding(
        self,
        *,
        spec: dict[str, Any],
        report: dict[str, Any],
        triage: dict[str, Any],
        seed_id: str,
    ) -> str | None:
        """Persist a finding; returns its id, or None if it is a duplicate."""
        kinds = divergence_kinds(report)
        detail = "; ".join(d.get("detail", "") for d in report.get("divergences", []))
        fp = fingerprint(kinds, detail, spec.get("solidity", ""))
        if fp in self.known_fingerprints():
            return None
        finding = {
            "id": fp,
            "ts": time.time(),
            "seed": seed_id,
            "name": spec.get("name"),
            "kinds": sorted(kinds),
            "fingerprint": fp,
            "triage": triage,
            "spec": spec,
            "tool_versions": report.get("tool_versions", {}),
        }
        self._append(self._findings, finding)
        report_path = self.root / "reports" / f"{fp}.json"
        report_path.write_text(json.dumps(report, indent=2))
        return fp

    def findings(self) -> list[dict[str, Any]]:
        if not self._findings.exists():
            return []
        return [
            json.loads(line) for line in self._findings.read_text().strip().splitlines()
        ]

    def get_finding(self, finding_id: str) -> dict[str, Any] | None:
        for f in self.findings():
            if f["id"] == finding_id:
                return f
        return None

    def report_for(self, finding_id: str) -> dict[str, Any] | None:
        path = self.root / "reports" / f"{finding_id}.json"
        return json.loads(path.read_text()) if path.exists() else None

    # --- seed coverage ------------------------------------------------------

    def seed_stats(self) -> dict[str, dict[str, Any]]:
        if not self._seeds_state.exists():
            return {}
        return json.loads(self._seeds_state.read_text())

    def note_seed_result(self, seed_id: str, kinds: set[str]) -> None:
        stats = self.seed_stats()
        entry = stats.setdefault(seed_id, {"probes": 0, "kinds_found": []})
        entry["probes"] += 1
        entry["kinds_found"] = sorted(set(entry["kinds_found"]) | kinds)
        self._seeds_state.write_text(json.dumps(stats, indent=2))

    # --- helpers ------------------------------------------------------------

    @staticmethod
    def _append(path: Path, obj: dict[str, Any]) -> None:
        with path.open("a") as f:
            f.write(json.dumps(obj) + "\n")
