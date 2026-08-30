"""Abstract chain adapter interface."""

from __future__ import annotations

import socket
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..accounts import LabelResolver
from ..schema import ChainStateSnapshot, DryRunOutcome, TxOutcome
from ..spec import ConstructorSpec, StepSpec


@dataclass
class DeployOutcome:
    status: str  # "success" | "revert" | "error"
    address: str | None = None
    tx_hash: str | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "address": self.address,
            "tx_hash": self.tx_hash,
            "error": self.error,
        }


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ChainAdapter(ABC):
    """One on-chain backend: manages a local node process and a deployed contract."""

    name: str = "abstract"

    def __init__(self, workdir: Path, labels: LabelResolver):
        self.workdir = workdir
        self.labels = labels
        self.proc: subprocess.Popen | None = None

    # -- lifecycle -----------------------------------------------------------

    @abstractmethod
    def start(self) -> None: ...

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def _spawn(self, cmd: list[str], log_name: str) -> None:
        # log file intentionally stays open for the lifetime of the node process
        log = open(self.workdir / log_name, "w")  # noqa: SIM115
        self.proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)

    def _wait_ready(self, probe, timeout: float = 60.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc and self.proc.poll() is not None:
                raise RuntimeError(
                    f"{self.name} node exited early (code {self.proc.returncode})"
                )
            try:
                if probe():
                    return
            except Exception:
                pass
            time.sleep(0.5)
        raise TimeoutError(f"{self.name} node did not become ready within {timeout}s")

    # -- contract lifecycle --------------------------------------------------

    @abstractmethod
    def deploy(
        self, artifacts: dict[str, Any], ctor: ConstructorSpec
    ) -> DeployOutcome: ...

    @abstractmethod
    def dry_run(self, step: StepSpec) -> DryRunOutcome: ...

    @abstractmethod
    def transact(self, step: StepSpec) -> TxOutcome: ...

    @abstractmethod
    def snapshot(self) -> ChainStateSnapshot: ...
