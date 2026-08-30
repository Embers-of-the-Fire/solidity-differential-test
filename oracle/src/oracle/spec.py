"""Test-environment specification loading and validation.

A test environment is a JSON document:

    {
      "name": "counter-basic",
      "solidity": "contract counter { ... }",        // or "source_file": "counter.sol"
      "contract": "counter",
      "constructor": {"name": "new", "args": [7]},    // args optional
      "solc":   {"optimizer": true, "optimizer_runs": 200},
      "solang": {"opt_level": "default"},
      "oracle": {"storage": "count", "events": true,
                 "revert_reasons": true, "gas": false},
      "steps": [
        {"action": "query", "function": "count"},
        {"action": "call", "function": "inc", "args": [5],
         "sender": "alice", "value": 0}
      ]
    }

Step fields:
  action   "call" (state-changing tx) or "query" (read-only dry run)
  function function name as declared in Solidity
  args     positional JSON args; "$label" resolves to a well-known account
  sender   account label ("deployer" default)
  value    native units sent with the call (wei on EVM, planck on Polkadot)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class StepSpec:
    action: str  # "call" | "query"
    function: str
    args: list[Any] = field(default_factory=list)
    sender: str = "deployer"
    value: int = 0


@dataclass
class ConstructorSpec:
    name: str | None = None
    args: list[Any] = field(default_factory=list)
    value: int = 0


@dataclass
class OracleConfig:
    storage: str = "count"  # "count" | "exact" | "off"
    events: bool = True
    revert_reasons: bool = True
    gas: bool = False


@dataclass
class TestSpec:
    name: str
    source: str
    contract: str
    constructor: ConstructorSpec
    steps: list[StepSpec]
    solc_settings: dict = field(default_factory=dict)
    solang_settings: dict = field(default_factory=dict)
    oracle: OracleConfig = field(default_factory=OracleConfig)


def load_test_spec(path: str | Path) -> TestSpec:
    path = Path(path)
    raw = json.loads(path.read_text())

    if "solidity" in raw:
        source = raw["solidity"]
    elif "source_file" in raw:
        source = (path.parent / raw["source_file"]).read_text()
    else:
        raise ValueError("spec must contain 'solidity' or 'source_file'")

    contract = raw.get("contract")
    if not contract:
        raise ValueError("spec must name the target 'contract'")

    ctor_raw = raw.get("constructor", {})
    constructor = ConstructorSpec(
        name=ctor_raw.get("name"),
        args=list(ctor_raw.get("args", [])),
        value=int(ctor_raw.get("value", 0)),
    )

    steps = []
    for i, s in enumerate(raw.get("steps", [])):
        action = s.get("action", "call")
        if action not in ("call", "query"):
            raise ValueError(f"step {i}: action must be 'call' or 'query'")
        if "function" not in s:
            raise ValueError(f"step {i}: missing 'function'")
        steps.append(
            StepSpec(
                action=action,
                function=s["function"],
                args=list(s.get("args", [])),
                sender=s.get("sender", "deployer"),
                value=int(s.get("value", 0)),
            )
        )

    oracle_raw = raw.get("oracle", {})
    oracle = OracleConfig(
        storage=oracle_raw.get("storage", "count"),
        events=bool(oracle_raw.get("events", True)),
        revert_reasons=bool(oracle_raw.get("revert_reasons", True)),
        gas=bool(oracle_raw.get("gas", False)),
    )
    if oracle.storage not in ("count", "exact", "off"):
        raise ValueError("oracle.storage must be 'count', 'exact' or 'off'")

    return TestSpec(
        name=raw.get("name", path.stem),
        source=source,
        contract=contract,
        constructor=constructor,
        steps=steps,
        solc_settings=dict(raw.get("solc", {})),
        solang_settings=dict(raw.get("solang", {})),
        oracle=oracle,
    )
