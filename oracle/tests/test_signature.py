"""Unit tests for the divergence-signature taxonomy (T0.1).

Covers every kind's relation taxonomy, the signature format, and the
compare.py creation sites that attach signatures to Divergence objects —
including label-mapped addresses (return payloads keep their value-free
shape even when address labels differ).
"""

from oracle.compare import compare_compile, compare_deploy, compare_step
from oracle.compilers import CompileOutcome
from oracle.schema import (
    ChainStateSnapshot,
    DryRunOutcome,
    StepChainResult,
    TxOutcome,
)
from oracle.signature import (
    format_signature,
    make_signature,
    parse_signature,
    reason_class,
    relation_for,
    value_shape,
)
from oracle.spec import OracleConfig

CONFIG = OracleConfig()


def step(
    chain: str,
    storage: dict[str, str] | None = None,
    dry_status: str = "success",
    return_value=None,
    revert_reason: str | None = None,
    return_data_raw: str | None = None,
    tx_status: str | None = "success",
    events: list[dict] | None = None,
) -> StepChainResult:
    return StepChainResult(
        chain=chain,
        dry_run=DryRunOutcome(
            dry_status,
            return_value=return_value,
            revert_reason=revert_reason,
            return_data_raw=return_data_raw,
        ),
        tx=(
            TxOutcome(tx_status, events=events or []) if tx_status is not None else None
        ),
        state=(
            ChainStateSnapshot(chain=chain, storage=storage)
            if tx_status is not None
            else None
        ),
    )


# --- pure helpers ------------------------------------------------------------


def test_value_shape_taxonomy():
    assert value_shape(None) == "null"
    assert value_shape(True) == "bool"
    assert value_shape(5) == "int"
    assert value_shape("0x0102") == "bytes"
    assert value_shape("hello") == "string"
    assert value_shape([1, 2]) == "tuple[2]"
    assert value_shape({"a": 1}) == "struct"


def test_reason_class_taxonomy():
    assert reason_class(None) == "none"
    assert reason_class("") == "none"
    assert reason_class("oops") == "error-string"
    assert reason_class("Panic(0x11)") == "panic:0x11"
    assert reason_class("Panic(0x01)") == "panic:0x01"
    # raw revert-data payloads (EVM big-endian word, solang SCALE LE tail)
    evm_raw = "0x4e487b71" + (0x11).to_bytes(32, "big").hex()
    assert reason_class(evm_raw) == "panic:0x11"
    solang_raw = "0x4e487b71" + (0x21).to_bytes(1, "little").hex()
    assert reason_class(solang_raw) == "panic:0x21"


def test_relation_compile_asymmetry():
    assert (
        relation_for("COMPILE_ASYMMETRY", {"solc_ok": False}, {"solang_ok": True})
        == "solc-rejects"
    )
    assert (
        relation_for("COMPILE_ASYMMETRY", {"solc_ok": True}, {"solang_ok": False})
        == "solang-rejects"
    )


def test_relation_status_pairs():
    assert (
        relation_for("DEPLOY_MISMATCH", {"status": "success"}, {"status": "error"})
        == "success≠error"
    )
    assert (
        relation_for("STATUS_MISMATCH", {"status": "revert"}, {"status": "success"})
        == "revert≠success"
    )
    assert relation_for("TX_STATUS_MISMATCH", "success", "revert") == "success≠revert"


def test_relation_return_shape_pair():
    assert relation_for("RETURN_MISMATCH", 1, 2) == "int≠int"
    assert relation_for("RETURN_MISMATCH", None, "0x0102") == "null≠bytes"
    assert relation_for("RETURN_MISMATCH", [1, 2], 3) == "tuple[2]≠int"


def test_relation_reason_class_pair():
    assert relation_for("REASON_MISMATCH", "Panic(0x11)", None) == "panic:0x11≠none"
    assert relation_for("REASON_MISMATCH", "a", "b") == "error-string≠error-string"


def test_relation_event_first_structural_difference():
    e1 = [{"name": "A", "args": [{"name": "x", "value": 1}]}]
    assert relation_for("EVENT_MISMATCH", e1, []) == "count"
    e2 = [{"name": "B", "args": [{"name": "x", "value": 1}]}]
    assert relation_for("EVENT_MISMATCH", e1, e2) == "name"
    e3 = [{"name": "A", "args": [{"name": "x", "value": 2}]}]
    assert relation_for("EVENT_MISMATCH", e1, e3) == "args"


def test_relation_storage_mode_tagged():
    count_payload = {"nonzero_entries": 1, "values": ["5"]}
    exact_payload = {"0x01": "0x05"}
    assert (
        relation_for("STORAGE_MISMATCH", count_payload, count_payload)
        == "multiset(count)"
    )
    assert (
        relation_for("STORAGE_MISMATCH", exact_payload, exact_payload) == "map(exact)"
    )


def test_format_and_parse_roundtrip():
    sig = format_signature("RETURN_MISMATCH", 3, "get", "int≠int")
    assert sig == "RETURN_MISMATCH|3|get|int≠int"
    assert parse_signature(sig) == {
        "kind": "RETURN_MISMATCH",
        "point": "3",
        "function": "get",
        "relation": "int≠int",
    }
    sig2 = format_signature("COMPILE_ASYMMETRY", "compile", None, "solc-rejects")
    assert sig2 == "COMPILE_ASYMMETRY|compile||solc-rejects"
    assert parse_signature(sig2)["function"] is None


def test_make_signature_composes():
    sig = make_signature("RETURN_MISMATCH", 0, "f", 1, None)
    assert sig == "RETURN_MISMATCH|0|f|int≠null"


# --- compare.py creation sites ------------------------------------------------


def test_compare_compile_signature():
    solc = CompileOutcome("solc", False, errors=["nope"])
    solang = CompileOutcome("solang", True)
    (d,) = compare_compile(solc, solang)
    assert d.point == "compile"
    assert d.signature == "COMPILE_ASYMMETRY|compile||solc-rejects"
    assert d.to_dict()["signature"] == d.signature


def test_compare_deploy_signature():
    (d,) = compare_deploy({"status": "success"}, {"status": "error"})
    assert d.point == "deploy"
    assert d.signature == "DEPLOY_MISMATCH|deploy||success≠error"


def test_compare_step_status_signature_carries_function():
    evm = step("evm", dry_status="success", tx_status=None)
    dot = step("polkadot", dry_status="revert", tx_status=None)
    divs = compare_step(2, evm, dot, CONFIG, function="f")
    assert divs[0].signature == "STATUS_MISMATCH|2|f|success≠revert"
    assert divs[0].point == 2


def test_compare_step_return_signature_is_value_free():
    evm = step("evm", return_value=41, tx_status=None)
    dot = step("polkadot", return_value=42, tx_status=None)
    (d,) = compare_step(0, evm, dot, CONFIG, function="get")
    assert d.signature == "RETURN_MISMATCH|0|get|int≠int"


def test_compare_step_return_signature_label_mapped_addresses():
    # label-mapped addresses normalize to hex strings on both chains; the
    # shape is "bytes" regardless of the concrete address value
    evm = step("evm", return_value="0x" + "aa" * 20, tx_status=None)
    dot = step("polkadot", return_value="0x" + "bb" * 20, tx_status=None)
    (d,) = compare_step(0, evm, dot, CONFIG, function="who")
    assert d.signature == "RETURN_MISMATCH|0|who|bytes≠bytes"


def test_compare_step_reason_signature():
    evm = step(
        "evm",
        dry_status="revert",
        revert_reason="Panic(0x11)",
        tx_status=None,
    )
    dot = step("polkadot", dry_status="revert", revert_reason=None, tx_status=None)
    (d,) = compare_step(1, evm, dot, CONFIG, function="f")
    assert d.signature == "REASON_MISMATCH|1|f|panic:0x11≠none"


def test_compare_step_event_signature():
    evm = step("evm", events=[{"name": "A", "args": [{"name": "x", "value": 1}]}])
    dot = step("polkadot", events=[])
    (d,) = compare_step(0, evm, dot, CONFIG, function="emit_it")
    assert d.signature == "EVENT_MISMATCH|0|emit_it|count"


def test_compare_step_storage_signature_count_mode():
    evm = step("evm", storage={"0x01": "0x" + (5).to_bytes(32, "big").hex()})
    dot = step("polkadot", storage={"0x01": "0x06"})
    d = [x for x in compare_step(0, evm, dot, CONFIG) if x.kind == "STORAGE_MISMATCH"]
    assert d[0].signature == "STORAGE_MISMATCH|0||multiset(count)"


def test_compare_step_storage_signature_exact_mode():
    cfg = OracleConfig(storage="exact")
    evm = step("evm", storage={"0x01": "0x" + (5).to_bytes(32, "big").hex()})
    dot = step("polkadot", storage={"0x01": "0x05"})
    d = [x for x in compare_step(0, evm, dot, cfg) if x.kind == "STORAGE_MISMATCH"]
    assert d[0].signature == "STORAGE_MISMATCH|0||map(exact)"


def test_compare_step_without_function_uses_empty():
    evm = step("evm", return_value=1, tx_status=None)
    dot = step("polkadot", return_value=2, tx_status=None)
    (d,) = compare_step(0, evm, dot, CONFIG)
    assert d.signature == "RETURN_MISMATCH|0||int≠int"
