from __future__ import annotations

import argparse
import json
import random

from .campaign import run_campaign
from .config import default_config
from .corpus import ensure_directories
from .generator import make_program_spec, render_case
from .mutators import mutate_spec
from .template_loader import build_environment


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="solidity-diff-fuzz")
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate = subparsers.add_parser("generate", help="Render one Solidity case")
    generate.add_argument("--seed", type=int, default=0)
    generate.add_argument("--case-index", type=int, default=0)
    generate.add_argument("--mutate", action="store_true")

    campaign = subparsers.add_parser(
        "campaign", help="Run a compile-only fuzz campaign"
    )
    campaign.add_argument("--iterations", type=int, default=10)
    campaign.add_argument("--seed", type=int, default=0)
    campaign.add_argument("--mutate-rounds", type=int, default=2)
    campaign.add_argument("--solang-target", default="evm")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    config = default_config()
    if args.command == "generate":
        config.seed = args.seed
        ensure_directories([config.artifact_dir, config.queue_dir])
        environment = build_environment(config.root_dir)
        rng = random.Random(args.seed)
        spec = make_program_spec(rng, args.case_index)
        if args.mutate:
            spec = mutate_spec(spec, rng)
        case = render_case(
            environment, spec, config.queue_dir, f"preview-{args.case_index}"
        )
        print(case.source)
        return
    if args.command == "campaign":
        config.seed = args.seed
        config.solang_target = args.solang_target
        findings = run_campaign(config, args.iterations, args.mutate_rounds)
        print(
            json.dumps(
                [
                    {
                        "case_id": record.case_id,
                        "kind": record.kind.value,
                        "signature": record.signature,
                        "summary": record.summary,
                    }
                    for record in findings
                ],
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
