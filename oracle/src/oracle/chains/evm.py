"""EVM chain adapter: solc-produced bytecode running on a local anvil node."""

from __future__ import annotations

from typing import Any

from eth_abi import decode as abi_decode
from eth_utils import event_abi_to_log_topic
from web3 import Web3
from web3.exceptions import ContractLogicError

from ..accounts import LabelResolver
from ..schema import ChainStateSnapshot, DryRunOutcome, TxOutcome, norm_value
from ..spec import ConstructorSpec, StepSpec
from .base import ChainAdapter, DeployOutcome, free_port

ERROR_SELECTOR = "08c379a0"
PANIC_SELECTOR = "4e487b71"


def convert_arg(value: Any, sol_type: str, labels: LabelResolver) -> Any:
    """Convert a JSON spec value to a Python value for web3, guided by the ABI type."""
    base = sol_type.split("[")[0]
    if sol_type.endswith("]"):  # array
        elem_type = sol_type[: sol_type.rindex("[")]
        return [convert_arg(v, elem_type, labels) for v in value]
    if base.startswith(("uint", "int")):
        return int(value)
    if base == "bool":
        return bool(value)
    if base == "address":
        if labels.is_label(value):
            return Web3.to_checksum_address(labels.evm_address(value))
        return Web3.to_checksum_address(value)
    if base == "string":
        return str(value)
    if base == "bytes" or base.startswith("bytes"):
        if isinstance(value, str):
            return bytes.fromhex(value.removeprefix("0x"))
        return bytes(value)
    raise ValueError(f"unsupported solidity type for spec args: {sol_type}")


def decode_revert_reason(data: bytes | None) -> str | None:
    """Decode standard EVM revert payloads: Error(string) and Panic(uint256)."""
    if not data:
        return None
    selector = data[:4].hex()
    if selector == ERROR_SELECTOR:
        try:
            (reason,) = abi_decode(["string"], data[4:])
            return reason
        except Exception:
            return None
    if selector == PANIC_SELECTOR:
        try:
            (code,) = abi_decode(["uint256"], data[4:])
            return f"Panic(0x{code:02x})"
        except Exception:
            return None
    return None


class AnvilChain(ChainAdapter):
    name = "evm"

    def __init__(self, workdir, labels: LabelResolver):
        super().__init__(workdir, labels)
        self.port: int | None = None
        self.w3: Web3 | None = None
        self.abi: list[dict] | None = None
        self.contract = None
        self.address: str | None = None
        self._event_by_topic: dict[bytes, dict] = {}
        self._storage: dict[
            str, str
        ] = {}  # cumulative post-state storage (written slots)

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> None:
        self.port = free_port()
        self._spawn(
            [
                "anvil",
                "--port",
                str(self.port),
                "--steps-tracing",
                "--silent",
                "--chain-id",
                "31337",
            ],
            "anvil.log",
        )
        self.w3 = Web3(
            Web3.HTTPProvider(
                f"http://127.0.0.1:{self.port}", request_kwargs={"timeout": 30}
            )
        )
        self._wait_ready(lambda: self.w3.is_connected())

    # -- helpers -------------------------------------------------------------

    def _function_abi(self, name: str, nargs: int | None = None) -> dict:
        candidates = [
            e
            for e in self.abi
            if e.get("type") == "function"
            and e.get("name") == name
            and (nargs is None or len(e.get("inputs", [])) == nargs)
        ]
        if not candidates:
            raise ValueError(f"function '{name}' with {nargs} args not in ABI")
        return candidates[0]

    def _encode_args(self, inputs: list[dict], args: list[Any]) -> list[Any]:
        if len(inputs) != len(args):
            raise ValueError(
                f"arity mismatch: ABI wants {len(inputs)}, spec gives {len(args)}"
            )
        return [
            convert_arg(a, i["type"], self.labels)
            for a, i in zip(args, inputs, strict=True)
        ]

    def _sender(self, label: str) -> str:
        return self.labels.accounts[label].evm_address

    # -- contract lifecycle --------------------------------------------------

    def deploy(self, artifacts: dict[str, Any], ctor: ConstructorSpec) -> DeployOutcome:
        self.abi = artifacts["abi"]
        self._event_by_topic = {
            event_abi_to_log_topic(e): e for e in self.abi if e.get("type") == "event"
        }
        factory = self.w3.eth.contract(abi=self.abi, bytecode=artifacts["bytecode"])
        ctor_abi = next(
            (e for e in self.abi if e.get("type") == "constructor"), {"inputs": []}
        )
        args = self._encode_args(ctor_abi.get("inputs", []), ctor.args)
        try:
            tx_hash = factory.constructor(*args).transact(
                {"from": self._sender("deployer"), "value": ctor.value}
            )
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
        except Exception as e:
            return DeployOutcome("error", error=str(e))
        if receipt.status != 1:
            return DeployOutcome(
                "revert", tx_hash=tx_hash.hex(), error="constructor reverted"
            )
        self.address = receipt.contractAddress
        self.contract = self.w3.eth.contract(address=self.address, abi=self.abi)
        self._merge_storage(receipt.transactionHash)
        return DeployOutcome("success", address=self.address, tx_hash=tx_hash.hex())

    def dry_run(self, step: StepSpec) -> DryRunOutcome:
        fn_abi = self._function_abi(step.function, len(step.args))
        args = self._encode_args(fn_abi.get("inputs", []), step.args)
        fn = self.contract.functions[step.function](*args)
        data = fn._encode_transaction_data()
        tx = {
            "to": self.address,
            "data": data,
            "from": self._sender(step.sender),
            "value": step.value,
        }
        try:
            raw = self.w3.eth.call(tx)
        except ContractLogicError as e:
            revert_data = self._extract_revert_data(e)
            return DryRunOutcome(
                "revert",
                revert_reason=decode_revert_reason(revert_data),
                return_data_raw="0x" + revert_data.hex() if revert_data else "0x",
                error=str(e) if revert_data is None else None,
            )
        except Exception as e:
            return DryRunOutcome("error", error=str(e))
        outputs = fn_abi.get("outputs", [])
        if not outputs:
            value: Any = None
        else:
            decoded = abi_decode([o["type"] for o in outputs], raw)
            value = list(decoded) if len(outputs) > 1 else decoded[0]
        return DryRunOutcome(
            "success",
            return_value=norm_value(value),
            return_data_raw="0x" + raw.hex(),
        )

    @staticmethod
    def _extract_revert_data(exc: ContractLogicError) -> bytes | None:
        data = exc.data
        if data is None:
            return None
        if isinstance(data, dict):  # some nodes wrap by error selector
            data = next(iter(data.values()), None)
        if isinstance(data, str):
            return bytes.fromhex(data.removeprefix("0x"))
        if isinstance(data, (bytes, bytearray)):
            return bytes(data)
        return None

    def transact(self, step: StepSpec) -> TxOutcome:
        fn_abi = self._function_abi(step.function, len(step.args))
        args = self._encode_args(fn_abi.get("inputs", []), step.args)
        fn = self.contract.functions[step.function](*args)
        try:
            tx_hash = fn.transact(
                {"from": self._sender(step.sender), "value": step.value}
            )
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
        except ContractLogicError as e:
            return TxOutcome("revert", error=str(e))
        except Exception as e:
            return TxOutcome("error", error=str(e))
        status = "success" if receipt.status == 1 else "revert"
        events = (
            [self._decode_log(log) for log in receipt.logs]
            if status == "success"
            else []
        )
        if status == "success":
            self._merge_storage(receipt.transactionHash)
        return TxOutcome(
            status,
            tx_hash=receipt.transactionHash.hex(),
            block_hash=receipt.blockHash.hex(),
            gas_used=receipt.gasUsed,
            events=events,
        )

    def _decode_log(self, log) -> dict:
        event_abi = self._event_by_topic.get(bytes(log.topics[0]))
        if event_abi is None:
            return {
                "name": None,
                "args": [],
                "raw_topics": [t.hex() for t in log.topics],
            }
        indexed = [i for i in event_abi["inputs"] if i.get("indexed")]
        plain = [i for i in event_abi["inputs"] if not i.get("indexed")]
        args = []
        for k, inp in enumerate(indexed):
            topic_word = log.topics[k + 1]
            if inp["type"] in ("string", "bytes") or "[" in inp["type"]:
                args.append(
                    {"name": inp["name"], "value": "0x" + bytes(topic_word).hex()}
                )
            else:
                (v,) = abi_decode([inp["type"]], bytes(topic_word))
                args.append({"name": inp["name"], "value": norm_value(v)})
        if plain:
            decoded = abi_decode([i["type"] for i in plain], bytes(log.data))
            for inp, v in zip(plain, decoded, strict=True):
                args.append({"name": inp["name"], "value": norm_value(v)})
        # restore declaration order
        order = {i["name"]: n for n, i in enumerate(event_abi["inputs"])}
        args.sort(key=lambda a: order[a["name"]])
        return {"name": event_abi["name"], "args": args}

    def _merge_storage(self, tx_hash: bytes) -> None:
        """Merge post-state storage diff of a tx into the cumulative storage map."""
        try:
            trace = self.w3.provider.make_request(
                "debug_traceTransaction",
                [
                    "0x" + tx_hash.hex(),
                    {"tracer": "prestateTracer", "tracerConfig": {"diffMode": True}},
                ],
            )
            post = trace["result"]["post"]
        except Exception:
            return  # storage tracing unavailable; leave map as-is
        for addr, entry in post.items():
            if self.address and addr.lower() == self.address.lower():
                for slot, value in entry.get("storage", {}).items():
                    self._storage[slot.lower()] = value.lower()

    def snapshot(self) -> ChainStateSnapshot:
        number = self.w3.eth.block_number
        block = self.w3.eth.get_block(number)
        return ChainStateSnapshot(
            chain=self.name,
            block_number=number,
            block_hash="0x" + block.hash.hex(),
            timestamp=block.timestamp,
            address=self.address,
            balance=self.w3.eth.get_balance(self.address),
            nonce=self.w3.eth.get_transaction_count(self.address),
            storage=dict(self._storage),
        )
