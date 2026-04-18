from __future__ import annotations

import json
import random
from pathlib import Path

from .compiler import compile_with_solang, compile_with_solc, ensure_compilers_available
from .config import CampaignConfig
from .corpus import (
    ensure_directories,
    load_existing_source_digests,
    load_known_signatures,
    persist_mismatch,
    source_digest,
)
from .generator import make_program_spec, render_case
from .models import MismatchRecord
from .mutators import mutate_spec
from .oracle import compare_results
from .template_loader import build_environment


def run_campaign(
    config: CampaignConfig, iterations: int, mutate_rounds: int = 1
) -> list[MismatchRecord]:
    ensure_compilers_available()
    ensure_directories(
        [
            config.artifact_dir,
            config.queue_dir,
            config.interesting_dir,
            config.crashes_dir,
            config.repro_dir,
        ]
    )
    rng = random.Random(config.seed)
    environment = build_environment(config.root_dir)
    findings: list[MismatchRecord] = []
    seen_source_digests = load_existing_source_digests(config.queue_dir)
    known_signatures = load_known_signatures(config.interesting_dir, config.crashes_dir)
    for index in range(iterations):
        spec = make_program_spec(rng, index)
        for mutation_index in range(mutate_rounds):
            if mutation_index > 0:
                spec = mutate_spec(spec, rng)
            case_id = f"case-{index:05d}-m{mutation_index}"
            case = render_case(environment, spec, config.queue_dir, case_id)
            digest = source_digest(case.source)
            if digest in seen_source_digests:
                case.source_path.unlink(missing_ok=True)
                continue
            seen_source_digests.add(digest)
            work_dir = config.queue_dir / case_id
            work_dir.mkdir(parents=True, exist_ok=True)
            solc = compile_with_solc(case.source_path, config, work_dir)
            solang = compile_with_solang(case.source_path, config, work_dir)
            mismatch = compare_results(case, solc, solang)
            _write_run_record(
                case_id, case.source, solc.to_json(), solang.to_json(), work_dir
            )
            if mismatch is not None:
                if mismatch.signature in known_signatures:
                    continue
                known_signatures.add(mismatch.signature)
                persist_mismatch(mismatch, config.interesting_dir, config.crashes_dir)
                findings.append(mismatch)
    return findings


def _write_run_record(
    case_id: str,
    source: str,
    solc: dict[str, object],
    solang: dict[str, object],
    work_dir: Path,
) -> None:
    record = {
        "case_id": case_id,
        "source": source,
        "solc": solc,
        "solang": solang,
    }
    (work_dir / "run.json").write_text(
        json.dumps(record, indent=2, sort_keys=True), encoding="utf-8"
    )
