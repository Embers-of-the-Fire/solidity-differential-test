"""Unit tests for compare_step: synthetic StepChainResult fixtures, no nodes.

Covers the known-artifact suppressions (dry-run dispatch error, error-vs-revert
tx status, bytes-return serialization) and the count-mode storage comparison
(signed-integer canonicalization, value-multiset semantics, None snapshots).
"""

from oracle.compare import compare_step
from oracle.schema import (
    ChainStateSnapshot,
    DryRunOutcome,
    StepChainResult,
    TxOutcome,
)
from oracle.spec import OracleConfig

CONFIG = OracleConfig()


def evm_word(value: int, signed: bool = False) -> str:
    return "0x" + value.to_bytes(32, "big", signed=signed).hex()


def step(
    chain: str,
    storage: dict[str, str] | None = None,
    dry_status: str = "success",
    dry_error: str | None = None,
    return_value=None,
    tx_status: str | None = "success",
) -> StepChainResult:
    return StepChainResult(
        chain=chain,
        dry_run=DryRunOutcome(dry_status, return_value=return_value, error=dry_error),
        tx=TxOutcome(tx_status) if tx_status is not None else None,
        state=(
            ChainStateSnapshot(chain=chain, storage=storage)
            if tx_status is not None
            else None
        ),
    )


def kinds(divs) -> set[str]:
    return {d.kind for d in divs}


# --- storage: count mode -----------------------------------------------------


def test_storage_endianness_same_value_no_divergence():
    evm = step("evm", storage={"0x01": evm_word(1000)})
    dot = step("polkadot", storage={"0x01": "0xe803"})  # 1000 SCALE LE u32
    assert not kinds(compare_step(0, evm, dot, CONFIG))


def test_storage_negative_int_same_value_no_divergence():
    evm = step("evm", storage={"0x01": evm_word(-4, signed=True)})
    dot = step("polkadot", storage={"0x01": "0xfcffffff"})  # -4 SCALE LE i32
    assert not kinds(compare_step(0, evm, dot, CONFIG))


def test_storage_packed_slot_with_zero_field_no_divergence():
    # solc packs a=5, b=0 into one word; solang gives each its own cell and
    # the zero cell is stripped by nonzero_storage
    evm = step("evm", storage={"0x00": evm_word(5)})
    dot = step("polkadot", storage={"0x01": "0x05", "0x02": "0x00000000"})
    assert not kinds(compare_step(0, evm, dot, CONFIG))


def test_storage_different_values_fire_with_count_context():
    evm = step("evm", storage={"0x01": evm_word(5), "0x02": evm_word(6)})
    dot = step("polkadot", storage={"0x01": "0x05"})
    divs = compare_step(0, evm, dot, CONFIG)
    assert kinds(divs) == {"STORAGE_MISMATCH"}
    d = divs[0]
    assert d.evm["nonzero_entries"] == 2
    assert d.polkadot["nonzero_entries"] == 1
    assert d.evm["values"] == ["5", "6"]


def test_storage_failed_snapshot_no_divergence():
    evm = step("evm", storage={"0x01": evm_word(5)})
    dot = step("polkadot", storage=None)  # snapshot failed
    assert not kinds(compare_step(0, evm, dot, CONFIG))
    dot2 = step("polkadot", storage={"0x01": "0x05"})
    evm2 = step("evm", storage=None)
    assert not kinds(compare_step(0, evm2, dot2, CONFIG))


def test_storage_exact_mode_compares_raw_maps():
    cfg = OracleConfig(storage="exact")
    evm = step("evm", storage={"0x01": evm_word(1000)})
    dot = step("polkadot", storage={"0x01": "0xe803"})
    assert "STORAGE_MISMATCH" in kinds(compare_step(0, evm, dot, cfg))


def test_storage_off_mode_skips_comparison():
    cfg = OracleConfig(storage="off")
    evm = step("evm", storage={"0x01": evm_word(1)})
    dot = step("polkadot", storage={"0x01": "0x02"})
    assert not kinds(compare_step(0, evm, dot, cfg))


# --- dry-run status: pallet dispatch-error artifact --------------------------


def test_dry_run_error_artifact_suppressed_when_tx_agrees():
    evm = step("evm", dry_status="success", tx_status="success")
    dot = step(
        "polkadot",
        dry_status="error",
        dry_error="0x0c0173796c6564",
        tx_status="success",
    )
    assert not kinds(compare_step(0, evm, dot, CONFIG))


def test_dry_run_error_artifact_suppressed_when_both_txs_revert():
    evm = step("evm", dry_status="revert", tx_status="revert")
    dot = step("polkadot", dry_status="error", dry_error="0x0c01", tx_status="revert")
    assert not kinds(compare_step(0, evm, dot, CONFIG))


def test_dry_run_error_fires_on_query_step():
    evm = step("evm", dry_status="success", tx_status=None)
    dot = step("polkadot", dry_status="error", dry_error="0x0c01", tx_status=None)
    assert "STATUS_MISMATCH" in kinds(compare_step(0, evm, dot, CONFIG))


def test_dry_run_error_fires_when_tx_statuses_differ():
    evm = step("evm", dry_status="success", tx_status="success")
    dot = step("polkadot", dry_status="error", dry_error="0x0c01", tx_status="revert")
    assert "STATUS_MISMATCH" in kinds(compare_step(0, evm, dot, CONFIG))


def test_dry_run_error_on_evm_side_not_suppressed():
    evm = step("evm", dry_status="error", dry_error="rpc boom", tx_status="success")
    dot = step("polkadot", dry_status="success", tx_status="success")
    assert "STATUS_MISMATCH" in kinds(compare_step(0, evm, dot, CONFIG))


# --- tx status: error-vs-revert suppression -----------------------------------


def test_tx_error_vs_revert_no_divergence():
    # nonpayable function called with value: both dry-runs revert, but anvil
    # labels the committed tx "error" where pallet-contracts reports "revert"
    evm = step("evm", dry_status="revert", tx_status="error")
    dot = step("polkadot", dry_status="revert", tx_status="revert")
    assert not kinds(compare_step(0, evm, dot, CONFIG))


def test_tx_success_vs_revert_fires():
    evm = step("evm", tx_status="success")
    dot = step("polkadot", tx_status="revert", dry_status="revert")
    assert "TX_STATUS_MISMATCH" in kinds(compare_step(0, evm, dot, CONFIG))


# --- return value: bytes serialization equivalence ----------------------------


def test_return_bytes_hex_vs_int_list_no_divergence():
    evm = step("evm", return_value="0x0102")
    dot = step("polkadot", return_value=[1, 2])
    assert not kinds(compare_step(0, evm, dot, CONFIG))


def test_return_bytes_different_content_fires():
    evm = step("evm", return_value="0x0102")
    dot = step("polkadot", return_value=[1, 3])
    assert "RETURN_MISMATCH" in kinds(compare_step(0, evm, dot, CONFIG))


def test_return_different_ints_still_fire():
    evm = step("evm", return_value=1)
    dot = step("polkadot", return_value=2)
    assert "RETURN_MISMATCH" in kinds(compare_step(0, evm, dot, CONFIG))
