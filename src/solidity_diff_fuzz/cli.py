from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from .campaign import run_campaign
from .compare import (
    compare_source_file,
    format_comparison_json,
    format_comparison_text,
    format_harness_check_text,
    run_harness_check,
)
from .config import default_config
from .corpus import ensure_directories
from .diff_test import (
    format_runtime_diff_json,
    format_runtime_diff_text,
    run_runtime_diff_test,
)
from .generator import make_program_spec, render_case
from .io_oracle import make_uint256_io_oracle
from .mutators import mutate_spec
from .runtime import format_runtime_smoke_text, run_runtime_smoke
from .target import format_target_check_json, format_target_check_text, run_target_check
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

    compare = subparsers.add_parser(
        "compare", help="Compare solc and solang compiler-observable outputs"
    )
    compare.add_argument("source", type=Path)
    compare.add_argument("--solang-target", default="evm")
    compare.add_argument("--work-dir", type=Path)
    compare.add_argument("--runtime", action="store_true")
    compare.add_argument("--calldata")
    compare.add_argument("--json", action="store_true")

    harness_check = subparsers.add_parser(
        "harness-check",
        help="Require both compile-time and runtime differential checks to pass",
    )
    harness_check.add_argument("source", type=Path)
    harness_check.add_argument("--solang-target", default="evm")
    harness_check.add_argument("--work-dir", type=Path)
    harness_check.add_argument("--calldata")
    harness_check.add_argument("--json", action="store_true")

    runtime_smoke = subparsers.add_parser(
        "runtime-smoke", help="Verify the local EVM runtime harness with solc bytecode"
    )
    runtime_smoke.add_argument("source", type=Path)
    runtime_smoke.add_argument("--work-dir", type=Path)
    runtime_smoke.add_argument("--json", action="store_true")

    target_check = subparsers.add_parser(
        "target-check",
        help="Compile both compilers and validate Solang supported-target artifacts",
    )
    target_check.add_argument("source", type=Path)
    target_check.add_argument("--solang-target", default="polkadot")
    target_check.add_argument("--work-dir", type=Path)
    target_check.add_argument("--json", action="store_true")

    runtime_diff = subparsers.add_parser(
        "runtime-diff",
        help=(
            "Run both compiler outputs and compare runtime behavior "
            "against expected output"
        ),
    )
    runtime_diff.add_argument("source", type=Path)
    runtime_diff.add_argument("--solang-target", default="evm")
    runtime_diff.add_argument("--calldata", required=True)
    runtime_diff.add_argument("--calldata-solang")
    runtime_diff.add_argument("--expect", required=True)
    runtime_diff.add_argument("--expect-solang")
    runtime_diff.add_argument("--work-dir", type=Path)
    runtime_diff.add_argument("--json", action="store_true")

    io_oracle = subparsers.add_parser(
        "io-oracle", help="Generate a uint256 input-output oracle Solidity contract"
    )
    io_oracle.add_argument("--expression", required=True)
    io_oracle.add_argument("--input", type=int, required=True)
    io_oracle.add_argument("--contract-name", default="GeneratedIoOracle")
    io_oracle.add_argument("--output", type=Path, required=True)
    io_oracle.add_argument("--json", action="store_true")

    io_diff = subparsers.add_parser(
        "io-diff", help="Generate and run a uint256 input-output runtime diff"
    )
    io_diff.add_argument("--expression", required=True)
    io_diff.add_argument("--input", type=int, required=True)
    io_diff.add_argument("--solang-target", default="polkadot")
    io_diff.add_argument("--contract-name", default="GeneratedIoOracle")
    io_diff.add_argument("--work-dir", type=Path)
    io_diff.add_argument("--json", action="store_true")

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
        return
    if args.command == "compare":
        config.solang_target = args.solang_target
        comparison = compare_source_file(
            args.source,
            config,
            args.work_dir,
            include_runtime=args.runtime,
            calldata=args.calldata,
        )
        if args.json:
            print(format_comparison_json(comparison))
        else:
            print(format_comparison_text(comparison))
        return
    if args.command == "harness-check":
        config.solang_target = args.solang_target
        check = run_harness_check(args.source, config, args.work_dir, args.calldata)
        if args.json:
            print(json.dumps(check.to_json(), indent=2, sort_keys=True))
        else:
            print(format_harness_check_text(check))
        raise SystemExit(0 if check.passed else 1)
    if args.command == "runtime-smoke":
        result = run_runtime_smoke(args.source, config, args.work_dir)
        if args.json:
            print(json.dumps(result.to_json(), indent=2, sort_keys=True))
        else:
            print(format_runtime_smoke_text(result))
        return
    if args.command == "target-check":
        config.solang_target = args.solang_target
        check = run_target_check(args.source, config, args.work_dir)
        if args.json:
            print(format_target_check_json(check))
        else:
            print(format_target_check_text(check))
        raise SystemExit(0 if check.passed else 1)
    if args.command == "runtime-diff":
        config.solang_target = args.solang_target
        result = run_runtime_diff_test(
            args.source,
            config,
            args.calldata,
            args.expect,
            args.expect_solang,
            args.calldata_solang,
            args.work_dir,
        )
        if args.json:
            print(format_runtime_diff_json(result))
        else:
            print(format_runtime_diff_text(result))
        raise SystemExit(0 if result.passed else 1)
    if args.command == "io-oracle":
        oracle = make_uint256_io_oracle(args.contract_name, args.expression, args.input)
        args.output.write_text(oracle.source, encoding="utf-8")
        metadata = {
            "source": str(args.output),
            "calldata_evm": oracle.calldata_evm,
            "calldata_solang_polkadot": oracle.calldata_solang_polkadot,
            "expect_evm": oracle.expect_evm,
            "expect_solang_polkadot": oracle.expect_solang_polkadot,
            "expected_value": oracle.expected_value,
        }
        if args.json:
            print(json.dumps(metadata, indent=2, sort_keys=True))
        else:
            print(f"source: {args.output}")
            print(f"calldata_evm: {oracle.calldata_evm}")
            print(f"calldata_solang_polkadot: {oracle.calldata_solang_polkadot}")
            print(f"expect_evm: {oracle.expect_evm}")
            print(f"expect_solang_polkadot: {oracle.expect_solang_polkadot}")
            print(f"expected_value: {oracle.expected_value}")
        return
    if args.command == "io-diff":
        config.solang_target = args.solang_target
        oracle = make_uint256_io_oracle(args.contract_name, args.expression, args.input)
        work_dir = args.work_dir or config.artifact_dir / "io-diff" / args.contract_name
        work_dir.mkdir(parents=True, exist_ok=True)
        source_path = work_dir / f"{args.contract_name}.sol"
        source_path.write_text(oracle.source, encoding="utf-8")
        calldata = (
            oracle.calldata_solang_polkadot
            if args.solang_target == "polkadot"
            else oracle.calldata_evm
        )
        result = run_runtime_diff_test(
            source_path,
            config,
            oracle.calldata_evm,
            oracle.expect_evm,
            oracle.expect_solang_polkadot,
            calldata,
            work_dir / "run",
        )
        if args.json:
            print(format_runtime_diff_json(result))
        else:
            print(format_runtime_diff_text(result))
        raise SystemExit(0 if result.passed else 1)


if __name__ == "__main__":
    main()
