"""Oracle comparator: cross-chain equivalence checks and divergence classification.

Divergence kinds:
  COMPILE_ASYMMETRY   one compiler rejects the source, the other accepts it
  DEPLOY_MISMATCH     deployment status differs
  STATUS_MISMATCH     dry-run status (success/revert/error) differs
  RETURN_MISMATCH     dry-run return values differ
  REASON_MISMATCH     revert reasons differ (both sides reverted)
  TX_STATUS_MISMATCH  committed-transaction status differs
  EVENT_MISMATCH      committed-transaction event logs differ
  STORAGE_MISMATCH    contract storage differs (mode: count/exact)
  GAS_MISMATCH        gas consumption differs (opt-in; gas models are different)

Known-artifact suppressions (raw values stay recorded in the report):
  - a pallet-contracts dry-run module-level error is not a STATUS_MISMATCH when
    the committed transaction agrees with the EVM (dry-run-only dispatch errors)
  - error-vs-revert committed statuses are both rejections, not a
    TX_STATUS_MISMATCH (storage/events are still compared)
  - RETURN_MISMATCH is suppressed when both return values are plainly the same
    byte content in different serializations (0x-hex vs SCALE Vec<u8> int list)
"""

from __future__ import annotations

from typing import Any, Literal

from .compilers import CompileOutcome
from .schema import (
    Divergence,
    StepChainResult,
    canonical_storage_value,
    nonzero_storage,
    strip_hex,
)
from .spec import OracleConfig


def compare_compile(solc: CompileOutcome, solang: CompileOutcome) -> list[Divergence]:
    if solc.ok == solang.ok:
        return []
    return [
        Divergence(
            "COMPILE_ASYMMETRY",
            step=None,
            detail="one compiler rejected the source while the other accepted it",
            evm={"solc_ok": solc.ok, "errors": solc.errors},
            polkadot={"solang_ok": solang.ok, "errors": solang.errors},
        )
    ]


def compare_deploy(evm: dict, polkadot: dict) -> list[Divergence]:
    if evm["status"] == polkadot["status"]:
        return []
    return [
        Divergence(
            "DEPLOY_MISMATCH",
            step=None,
            detail="deployment status differs",
            evm=evm,
            polkadot=polkadot,
        )
    ]


def _norm_reason(reason: str | None) -> str | None:
    return reason if reason else None


def _events_equal(a: list[dict], b: list[dict]) -> bool:
    if len(a) != len(b):
        return False
    for ea, eb in zip(a, b, strict=True):
        if ea.get("name") != eb.get("name"):
            return False
        va = [x["value"] for x in ea.get("args", [])]
        vb = [x["value"] for x in eb.get("args", [])]
        if va != vb:
            return False
    return True


def _storage_summary(
    storage: dict[str, str] | None, mode: str, byteorder: Literal["big", "little"]
) -> Any:
    if storage is None:
        return None  # snapshot failed; recorded as-is, never compared
    nz = nonzero_storage(storage)
    if mode == "exact":
        return nz
    # "count" mode: only the canonical value multiset is compared; the entry
    # count is context (slot packing makes counts layout-dependent)
    return {
        "nonzero_entries": len(nz),
        "values": sorted(canonical_storage_value(v, byteorder) for v in nz.values()),
    }


def _as_bytes(v: Any) -> bytes | None:
    """Interpret a decoded return value as raw bytes when it is plainly byte
    content: a 0x-hex string (EVM ABI) or a list of byte-sized ints (SCALE
    Vec<u8>). Anything else (strings, ints, tuples of mixed types) is not
    byte content and returns None."""
    if isinstance(v, str) and v.startswith("0x"):
        try:
            return bytes.fromhex(strip_hex(v))
        except ValueError:
            return None
    if isinstance(v, list) and all(isinstance(x, int) and 0 <= x <= 0xFF for x in v):
        return bytes(v)
    return None


def _dry_run_error_artifact(evm: StepChainResult, polkadot: StepChainResult) -> bool:
    """pallet-contracts dry-run (ContractsApi_call) can fail with a module-level
    dispatch error (undecoded SCALE blob) on calls whose committed transaction
    succeeds and matches the EVM. The committed tx is ground truth — its status,
    events and storage are compared separately — so the spurious dry-run status
    is suppressed. The raw error blob stays recorded in the report."""
    if polkadot.dry_run.status != "error":
        return False
    if evm.tx is None or polkadot.tx is None:
        return False  # query step: no committed tx to corroborate
    return evm.tx.status == polkadot.tx.status and evm.tx.status != "error"


def compare_step(
    index: int, evm: StepChainResult, polkadot: StepChainResult, config: OracleConfig
) -> list[Divergence]:
    divs: list[Divergence] = []

    # --- dry-run (status, return value, revert reason) -----------------------
    if evm.dry_run.status != polkadot.dry_run.status:
        if not _dry_run_error_artifact(evm, polkadot):
            divs.append(
                Divergence(
                    "STATUS_MISMATCH",
                    step=index,
                    detail="dry-run status differs",
                    evm={"status": evm.dry_run.status, "error": evm.dry_run.error},
                    polkadot={
                        "status": polkadot.dry_run.status,
                        "error": polkadot.dry_run.error,
                    },
                )
            )
    elif evm.dry_run.status == "success":
        if evm.dry_run.return_value != polkadot.dry_run.return_value:
            ba = _as_bytes(evm.dry_run.return_value)
            bb = _as_bytes(polkadot.dry_run.return_value)
            if not (ba is not None and bb is not None and ba == bb):
                divs.append(
                    Divergence(
                        "RETURN_MISMATCH",
                        step=index,
                        detail="dry-run return values differ",
                        evm=evm.dry_run.return_value,
                        polkadot=polkadot.dry_run.return_value,
                    )
                )
    elif evm.dry_run.status == "revert" and config.revert_reasons:
        ra, rb = (
            _norm_reason(evm.dry_run.revert_reason),
            _norm_reason(polkadot.dry_run.revert_reason),
        )
        if ra != rb:
            divs.append(
                Divergence(
                    "REASON_MISMATCH",
                    step=index,
                    detail="both sides reverted with different reasons",
                    evm=ra or evm.dry_run.return_data_raw,
                    polkadot=rb or polkadot.dry_run.return_data_raw,
                )
            )

    if evm.tx is None or polkadot.tx is None:
        return divs  # query step: nothing committed

    # --- committed transaction (status, events, gas) -------------------------
    # error and revert are both rejections (no state change); anvil labels e.g.
    # a nonpayable function called with value "error" where pallet-contracts
    # reports "revert". Only a committed-vs-rejected split is a divergence.
    if evm.tx.status != polkadot.tx.status and not (
        evm.tx.status in ("revert", "error")
        and polkadot.tx.status in ("revert", "error")
    ):
        divs.append(
            Divergence(
                "TX_STATUS_MISMATCH",
                step=index,
                detail="committed transaction status differs",
                evm=evm.tx.status,
                polkadot=polkadot.tx.status,
            )
        )
    if config.events and not _events_equal(evm.tx.events, polkadot.tx.events):
        divs.append(
            Divergence(
                "EVENT_MISMATCH",
                step=index,
                detail="emitted events differ",
                evm=evm.tx.events,
                polkadot=polkadot.tx.events,
            )
        )
    if config.gas and evm.tx.gas_used != polkadot.tx.gas_used:
        divs.append(
            Divergence(
                "GAS_MISMATCH",
                step=index,
                detail="gas consumption differs (note: different gas models)",
                evm=evm.tx.gas_used,
                polkadot=polkadot.tx.gas_used,
            )
        )

    # --- post-tx storage ------------------------------------------------------
    if config.storage != "off":
        sa = _storage_summary(
            evm.state.storage if evm.state else None, config.storage, "big"
        )
        sb = _storage_summary(
            polkadot.state.storage if polkadot.state else None, config.storage, "little"
        )
        if sa is not None and sb is not None:
            differ = (
                sa != sb if config.storage == "exact" else sa["values"] != sb["values"]
            )
            if differ:
                divs.append(
                    Divergence(
                        "STORAGE_MISMATCH",
                        step=index,
                        detail=f"contract storage differs (mode={config.storage})",
                        evm=sa,
                        polkadot=sb,
                    )
                )
    return divs
