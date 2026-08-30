"""Differential runner: compile, deploy and execute a test spec on both chains."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from .accounts import LabelResolver, default_accounts
from .chains import AnvilChain, ChainAdapter, ContractsNodeChain
from .compare import compare_compile, compare_deploy, compare_step
from .compilers import CompileOutcome, compile_solang, compile_solc, tool_versions
from .schema import Divergence, StepChainResult, dumps
from .spec import TestSpec


class DifferentialRunner:
    def __init__(
        self, spec: TestSpec, workdir: str | Path | None = None, verbose: bool = False
    ):
        self.spec = spec
        self.verbose = verbose
        self.workdir = (
            Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="oracle-run-"))
        )
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.labels = LabelResolver(default_accounts())
        self.evm = AnvilChain(self.workdir, self.labels)
        self.polkadot = ContractsNodeChain(self.workdir, self.labels)

    def log(self, msg: str) -> None:
        if self.verbose:
            print(f"[oracle] {msg}")

    def run(self) -> dict[str, Any]:
        spec = self.spec
        report: dict[str, Any] = {
            "name": spec.name,
            "contract": spec.contract,
            "tool_versions": tool_versions(),
            "oracle_config": {
                "storage": spec.oracle.storage,
                "events": spec.oracle.events,
                "revert_reasons": spec.oracle.revert_reasons,
                "gas": spec.oracle.gas,
            },
            "workdir": str(self.workdir),
            "compile": {},
            "deploy": {},
            "steps": [],
            "divergences": [],
            "verdict": "ERROR",
        }
        divergences: list[Divergence] = []

        # --- compile stage ---------------------------------------------------
        self.log("compiling with solc ...")
        solc_out = compile_solc(spec.source, spec.contract, spec.solc_settings)
        self.log("compiling with solang ...")
        solang_out = compile_solang(spec.source, spec.contract, spec.solang_settings)
        report["compile"] = {"solc": solc_out.to_dict(), "solang": solang_out.to_dict()}
        divergences.extend(compare_compile(solc_out, solang_out))
        if not solc_out.ok or not solang_out.ok:
            report["divergences"] = [d.to_dict() for d in divergences]
            report["verdict"] = "DIVERGENCE" if divergences else "PASS"
            return report

        # --- on-chain stage --------------------------------------------------
        chains: dict[str, ChainAdapter] = {"evm": self.evm, "polkadot": self.polkadot}
        artifacts = {"evm": solc_out.artifacts, "polkadot": solang_out.artifacts}
        try:
            for name, chain in chains.items():
                self.log(f"starting {name} node ...")
                chain.start()
                self.log(f"deploying on {name} ...")
                outcome = chain.deploy(artifacts[name], spec.constructor)
                report["deploy"][name] = outcome.to_dict()
                if outcome.status != "success":
                    self.log(f"deploy on {name} failed: {outcome.error}")
            divergences.extend(
                compare_deploy(report["deploy"]["evm"], report["deploy"]["polkadot"])
            )
            if self.evm.address and self.polkadot.address:
                self.labels.register_contract(self.evm.address, self.polkadot.address)
            deployed = all(report["deploy"][n]["status"] == "success" for n in chains)

            if deployed:
                for i, step in enumerate(spec.steps):
                    self.log(f"step {i}: {step.action} {step.function}({step.args})")
                    step_report: dict[str, Any] = {
                        "index": i,
                        "action": step.action,
                        "function": step.function,
                        "args": step.args,
                        "sender": step.sender,
                        "value": step.value,
                    }
                    results: dict[str, StepChainResult] = {}
                    for name, chain in chains.items():
                        dry = chain.dry_run(step)
                        tx = chain.transact(step) if step.action == "call" else None
                        state = chain.snapshot() if step.action == "call" else None
                        results[name] = StepChainResult(
                            chain=name, dry_run=dry, tx=tx, state=state
                        )
                        step_report[name] = results[name].to_dict()
                    step_divs = compare_step(
                        i, results["evm"], results["polkadot"], spec.oracle
                    )
                    for d in step_divs:
                        self.log(f"  DIVERGENCE {d.kind}: {d.detail}")
                    step_report["divergences"] = [d.to_dict() for d in step_divs]
                    divergences.extend(step_divs)
                    report["steps"].append(step_report)
            else:
                report["steps_skipped"] = "deployment failed on at least one chain"
        finally:
            for chain in chains.values():
                chain.stop()

        report["divergences"] = [d.to_dict() for d in divergences]
        report["verdict"] = "DIVERGENCE" if divergences else "PASS"
        return report


def run_spec(
    spec: TestSpec, workdir: str | Path | None = None, verbose: bool = False
) -> dict:
    return DifferentialRunner(spec, workdir=workdir, verbose=verbose).run()


__all__ = ["CompileOutcome", "DifferentialRunner", "dumps", "run_spec"]
