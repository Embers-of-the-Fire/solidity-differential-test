"""Chain-agnostic block-state schema and execution outcome types.

The block state schema is deliberately minimal (the oracle defines it; the
chains only have to fill it in):

    ChainStateSnapshot = {
        "chain":    "evm" | "polkadot",
        "block":    {"number": int, "hash": "0x..", "timestamp": int | null},
        "contract": {"address": str, "balance": str, "nonce": int | null},
        "storage":  {"0x<key>": "0x<value>"} | null   # raw, chain-specific encoding
    }

Oracle-relevant comparison fields are the per-step outcomes (status, return
value, revert reason, events) plus the contract storage map. Block metadata is
recorded for traceability but never compared.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# normalization helpers


def norm_value(v: Any) -> Any:
    """Convert decoded values to JSON-safe, comparable forms."""
    if isinstance(v, (bytes, bytearray)):
        return "0x" + bytes(v).hex()
    if isinstance(v, bool) or v is None or isinstance(v, (int, str)):
        return v
    if isinstance(v, (list, tuple)):
        return [norm_value(x) for x in v]
    if isinstance(v, dict):
        return {str(k): norm_value(val) for k, val in v.items()}
    return str(v)


def strip_hex(s: str) -> str:
    return s.removeprefix("0x")


def normalize_storage_value(hex_value: str) -> str:
    """Endianness-agnostic-ish normalization for storage comparison.

    EVM words are big-endian 32-byte, pallet-contracts values are raw bytes
    (SCALE little-endian for ints). Stripping zero bytes from *both* ends makes
    single-byte values comparable across chains; multi-byte comparisons remain
    heuristic (documented in the README).
    """
    raw = bytes.fromhex(strip_hex(hex_value))
    stripped = raw.strip(b"\x00")
    return "0x" + stripped.hex() if stripped else "0x"


def nonzero_storage(storage: dict[str, str] | None) -> dict[str, str]:
    if not storage:
        return {}
    return {
        k.lower(): v.lower()
        for k, v in storage.items()
        if bytes.fromhex(strip_hex(v)).strip(b"\x00")
    }


# ---------------------------------------------------------------------------
# outcomes


@dataclass
class DryRunOutcome:
    status: str  # "success" | "revert" | "error"
    return_value: Any = None
    revert_reason: str | None = None
    return_data_raw: str | None = None
    debug_message: str | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "return_value": norm_value(self.return_value),
            "revert_reason": self.revert_reason,
            "return_data_raw": self.return_data_raw,
            "debug_message": self.debug_message,
            "error": self.error,
        }


@dataclass
class TxOutcome:
    status: str  # "success" | "revert" | "error"
    tx_hash: str | None = None
    block_hash: str | None = None
    gas_used: int | None = None
    events: list[dict] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "tx_hash": self.tx_hash,
            "block_hash": self.block_hash,
            "gas_used": self.gas_used,
            "events": norm_value(self.events),
            "error": self.error,
        }


@dataclass
class ChainStateSnapshot:
    chain: str
    block_number: int | None = None
    block_hash: str | None = None
    timestamp: int | None = None
    address: str | None = None
    balance: int | None = None
    nonce: int | None = None
    storage: dict[str, str] | None = None

    def to_dict(self) -> dict:
        return {
            "chain": self.chain,
            "block": {
                "number": self.block_number,
                "hash": self.block_hash,
                "timestamp": self.timestamp,
            },
            "contract": {
                "address": self.address,
                "balance": str(self.balance) if self.balance is not None else None,
                "nonce": self.nonce,
            },
            "storage": self.storage,
        }


@dataclass
class StepChainResult:
    chain: str
    dry_run: DryRunOutcome
    tx: TxOutcome | None = None  # only for "call" actions
    state: ChainStateSnapshot | None = None  # post-tx snapshot, only for "call"

    def to_dict(self) -> dict:
        d = {"chain": self.chain, "dry_run": self.dry_run.to_dict()}
        if self.tx is not None:
            d["tx"] = self.tx.to_dict()
        if self.state is not None:
            d["state"] = self.state.to_dict()
        return d


@dataclass
class Divergence:
    kind: str
    step: int | None
    detail: str
    evm: Any = None
    polkadot: Any = None

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "step": self.step,
            "detail": self.detail,
            "evm": norm_value(self.evm),
            "polkadot": norm_value(self.polkadot),
        }


class NpEncoder(json.JSONEncoder):
    def default(self, o: Any) -> Any:
        if isinstance(o, (bytes, bytearray)):
            return "0x" + bytes(o).hex()
        return super().default(o)


def dumps(obj: Any, **kwargs: Any) -> str:
    return json.dumps(obj, cls=NpEncoder, **kwargs)
