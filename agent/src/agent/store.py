"""Findings store: append-only JSONL, fingerprint dedup.

Layout under the findings dir:

    probes.jsonl      every probe: identity, verdict, triage, discovery counters
    artifacts/probes/<probe-id>/{spec,report}.json
                      full evidence for every divergence, including rejected ones
    findings.jsonl    accepted findings (bug candidates), one per line
    corpus.jsonl      admitted specs with lineage/energy (see corpus.py)
    reports/<id>.json full oracle report for each finding
    campaign.json     frozen run configuration and tool/seed provenance
    review/           offline screening and separate human decisions
    seeds_state.json  per-seed coverage stats (probes run, kinds found)

Kept dependency-free (no SQLite): the volume is low and JSONL is greppable,
diff-able and trivially replayable.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import Any

from .corpus import Corpus
from .executor import divergence_kinds, divergence_signatures, earliest_signature
from .usage import summarize_jsonl


def fingerprint(signatures: set[str]) -> str:
    """Stable dedup key: sha1 over the sorted divergence-signature set.

    Deliberately excludes source text and payload values (T0.2/D2): a bug is
    its signature set, not its spelling. One-time migration of pre-signature
    findings is handled by agent/tools/refingerprint.py.
    """
    h = hashlib.sha1()
    h.update("\n".join(sorted(signatures)).encode())
    return h.hexdigest()[:16]


class FindingStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "reports").mkdir(exist_ok=True)
        self._probes = self.root / "probes.jsonl"
        self._findings = self.root / "findings.jsonl"
        self._seeds_state = self.root / "seeds_state.json"
        self.corpus = Corpus(self.root / "corpus.jsonl")

    # --- probes -------------------------------------------------------------

    def record_probe(
        self,
        *,
        spec: dict[str, Any],
        report: dict[str, Any],
        seed_id: str,
        category: str,
        timing: dict[str, Any] | None = None,
        usage: dict[str, Any] | None = None,
        oracle_runs_total: int | None = None,
        llm_calls_total: int | None = None,
        llm_tokens_total: int | None = None,
        parent_id: str | None = None,
        origin: str = "generated",
    ) -> str:
        """Record one probe and retain full evidence for every divergence.

        The returned ID links later minimized findings to the first-witness
        execution. Legacy non-divergent probes remain compact: their specs and
        reports are not written to disk.
        """
        probe_id = uuid.uuid4().hex
        record = {
            "probe_id": probe_id,
            "ts": time.time(),
            "seed": seed_id,
            "name": spec.get("name"),
            "verdict": report.get("verdict"),
            "category": category,
            "kinds": sorted(divergence_kinds(report)),
            "earliest_signature": earliest_signature(report),
            "parent_id": parent_id,
            "origin": origin,
            "timing": timing,
            "usage": usage,
            "oracle_runs_total": oracle_runs_total,
            "llm_calls_total": llm_calls_total,
            "llm_tokens_total": llm_tokens_total,
        }
        if report.get("verdict") == "DIVERGENCE":
            artifact_dir = self.root / "artifacts" / "probes" / probe_id
            artifact_dir.mkdir(parents=True, exist_ok=True)
            spec_path = artifact_dir / "spec.json"
            report_path = artifact_dir / "report.json"
            spec_path.write_text(json.dumps(spec, indent=2) + "\n")
            report_path.write_text(json.dumps(report, indent=2) + "\n")
            record["spec_path"] = str(spec_path.relative_to(self.root))
            record["report_path"] = str(report_path.relative_to(self.root))
        self._append(self._probes, record)
        return probe_id

    def recent_probes(self, n: int = 15) -> list[dict[str, Any]]:
        if not self._probes.exists():
            return []
        lines = self._probes.read_text().strip().splitlines()
        return [json.loads(line) for line in lines[-n:]]

    def probes(self) -> list[dict[str, Any]]:
        if not self._probes.exists():
            return []
        return [
            json.loads(line)
            for line in self._probes.read_text().strip().splitlines()
            if line.strip()
        ]

    # --- usage / cost -------------------------------------------------------

    def usage_summary(self) -> dict[str, Any]:
        """Aggregate the per-call usage log (llm_usage.jsonl)."""
        return summarize_jsonl(self.root / "llm_usage.jsonl")

    # --- findings -----------------------------------------------------------

    def known_fingerprints(self) -> set[str]:
        if not self._findings.exists():
            return set()
        return {
            json.loads(line)["fingerprint"]
            for line in self._findings.read_text().strip().splitlines()
        }

    def known_signatures(self) -> set[str]:
        """Earliest signatures of all stored findings (cheap pre-minimize dedup)."""
        sigs: set[str] = set()
        for f in self.findings():
            sig = f.get("earliest_signature")
            if sig:
                sigs.add(sig)
        return sigs

    def add_finding(
        self,
        *,
        spec: dict[str, Any],
        report: dict[str, Any],
        triage: dict[str, Any],
        seed_id: str,
        timing: dict[str, Any] | None = None,
        usage: dict[str, Any] | None = None,
        oracle_runs_total: int | None = None,
        llm_calls_total: int | None = None,
        minimality: dict[str, Any] | None = None,
        original_spec: dict[str, Any] | None = None,
        origin_probe_id: str | None = None,
    ) -> str | None:
        """Persist a finding; returns its id, or None if it is a duplicate."""
        sigs = divergence_signatures(report)
        fp = fingerprint(sigs)
        if fp in self.known_fingerprints():
            return None
        finding = {
            "id": fp,
            "ts": time.time(),
            "seed": seed_id,
            "name": spec.get("name"),
            "kinds": sorted(divergence_kinds(report)),
            "signatures": sorted(sigs),
            "earliest_signature": earliest_signature(report),
            "fingerprint": fp,
            "triage": triage,
            "spec": spec,
            "tool_versions": report.get("tool_versions", {}),
            "timing": timing,
            "usage": usage,
            "oracle_runs_total": oracle_runs_total,
            "llm_calls_total": llm_calls_total,
            "minimality": minimality,
            "original_spec": original_spec,
            "origin_probe_id": origin_probe_id,
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
