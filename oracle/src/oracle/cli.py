"""Command-line interface for the differential oracle."""

from __future__ import annotations

import argparse
import sys

from .report import write_json, write_markdown
from .runner import DifferentialRunner
from .spec import load_test_spec


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="solidity-diff-oracle",
        description="On-chain differential testing oracle: solc (EVM/anvil) vs solang (Polkadot/pallet-contracts)",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run a test environment and produce a report")
    run.add_argument("spec", help="path to the test environment JSON spec")
    run.add_argument("--json", metavar="PATH", help="write JSON report to PATH")
    run.add_argument("--md", metavar="PATH", help="write Markdown report to PATH")
    run.add_argument(
        "--workdir", metavar="DIR", help="working dir for node logs and artifacts"
    )
    run.add_argument("--quiet", action="store_true", help="suppress progress output")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "run":
        spec = load_test_spec(args.spec)
        runner = DifferentialRunner(spec, workdir=args.workdir, verbose=not args.quiet)
        report = runner.run()

        if args.json:
            write_json(report, args.json)
        else:
            default_json = str(runner.workdir / "report.json")
            write_json(report, default_json)
            print(f"JSON report: {default_json}")
        if args.md:
            write_markdown(report, args.md)
            print(f"Markdown report: {args.md}")

        print(
            f"\nverdict: {report['verdict']} ({len(report['divergences'])} divergence(s))"
        )
        for d in report["divergences"]:
            where = f"step {d['step']}" if d["step"] is not None else "setup"
            print(f"  - {d['kind']} ({where}): {d['detail']}")
        return 0 if report["verdict"] == "PASS" else 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
