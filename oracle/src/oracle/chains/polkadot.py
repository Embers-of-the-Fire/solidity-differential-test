"""Polkadot chain adapter: solang-produced WASM on a local substrate-contracts-node."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from scalecodec.base import ScaleBytes
from scalecodec.utils.ss58 import ss58_decode
from substrateinterface import Keypair, SubstrateInterface
from substrateinterface.contracts import ContractCode

from ..accounts import LabelResolver
from ..scalemini import (
    REVERT_FLAG,
    decode_contract_exec_result,
    decode_revert_reason,
    encode_contracts_api_call,
)
from ..schema import ChainStateSnapshot, DryRunOutcome, TxOutcome, norm_value
from ..spec import ConstructorSpec, StepSpec
from .base import ChainAdapter, DeployOutcome, free_port

GENEROUS_GAS = {"ref_time": 900_000_000_000, "proof_size": 8_000_000}
CHILD_STORAGE_PREFIX = b":child_storage:default:"


class ContractsNodeChain(ChainAdapter):
    name = "polkadot"

    def __init__(self, workdir, labels: LabelResolver):
        super().__init__(workdir, labels)
        self.port: int | None = None
        self.substrate: SubstrateInterface | None = None
        self.contract = None
        self.address: str | None = None
        self._keypairs: dict[str, Keypair] = {}

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> None:
        self.port = free_port()
        self._spawn(
            ["substrate-contracts-node", "--dev", "--tmp", f"--rpc-port={self.port}"],
            "substrate-contracts-node.log",
        )

        def probe() -> bool:
            try:
                self.substrate = SubstrateInterface(url=f"ws://127.0.0.1:{self.port}")
                return True
            except Exception:
                return False

        self._wait_ready(probe)
        for label, account in self.labels.accounts.items():
            kp = Keypair.create_from_uri(account.substrate_uri)
            account.ss58_address = kp.ss58_address
            self.labels.register_ss58(label, kp.ss58_address)
            self._keypairs[label] = kp

    # -- helpers -------------------------------------------------------------

    def _message_abi(self, name: str, nargs: int | None = None) -> dict:
        candidates = [
            m
            for m in self.contract.metadata.metadata_dict["spec"]["messages"]
            if m["label"] == name and (nargs is None or len(m.get("args", [])) == nargs)
        ]
        if not candidates:
            raise ValueError(f"message '{name}' with {nargs} args not in metadata")
        return candidates[0]

    def _encode_args_dict(self, params: list[dict], args: list[Any]) -> dict:
        if len(params) != len(args):
            raise ValueError(
                f"arity mismatch: metadata wants {len(params)}, spec gives {len(args)}"
            )
        return {
            p["label"]: self._convert_arg(a) for a, p in zip(args, params, strict=True)
        }

    def _convert_arg(self, value: Any) -> Any:
        """JSON spec value -> python value acceptable to scalecodec for contract types."""
        if self.labels.is_label(value):
            return self.labels.accounts[value[1:]].ss58_address
        if isinstance(value, (bool, int)):
            return value
        if isinstance(value, str):
            return value  # strings and "0x.." hex bytes are handled by scalecodec
        if isinstance(value, list):
            return [self._convert_arg(v) for v in value]
        return value

    def _keypair(self, label: str) -> Keypair:
        return self._keypairs[label]

    def _decode_return_value(self, method: str, data: bytes) -> Any:
        type_string = self.contract.metadata.get_return_type_string_for_message(method)
        if type_string is None:
            return None
        obj = self.substrate.create_scale_object(type_string)
        obj.decode(ScaleBytes(data))
        return norm_value(obj.value)

    # -- contract lifecycle --------------------------------------------------

    def deploy(self, artifacts: dict[str, Any], ctor: ConstructorSpec) -> DeployOutcome:
        tmp = Path(tempfile.mkdtemp(prefix="oracle-dot-", dir=self.workdir))
        wasm_path = tmp / "contract.wasm"
        meta_path = tmp / "contract.json"
        wasm_path.write_bytes(artifacts["wasm"])
        meta_path.write_text(json.dumps(artifacts["metadata"]))

        code = ContractCode.create_from_contract_files(
            wasm_file=str(wasm_path),
            metadata_file=str(meta_path),
            substrate=self.substrate,
        )
        ctors = artifacts["metadata"]["spec"]["constructors"]
        ctor_meta = None
        if ctor.name:
            ctor_meta = next((c for c in ctors if c["label"] == ctor.name), None)
            if ctor_meta is None:
                return DeployOutcome(
                    "error", error=f"constructor '{ctor.name}' not in metadata"
                )
        elif len(ctors) == 1:
            ctor_meta = ctors[0]
        else:
            ctor_meta = next((c for c in ctors if c["label"] == "new"), ctors[0])
        args = self._encode_args_dict(ctor_meta.get("args", []), ctor.args)
        try:
            self.contract = code.deploy(
                self._keypair("deployer"),
                ctor_meta["label"],
                args=args,
                value=ctor.value,
                upload_code=True,
                gas_limit=GENEROUS_GAS,
                deployment_salt="0x" + os.urandom(32).hex(),
            )
        except Exception as e:
            msg = str(e)
            status = "revert" if "Reverted" in msg or "Trapped" in msg else "error"
            return DeployOutcome(status, error=msg)
        self.address = self.contract.contract_address
        return DeployOutcome("success", address=self.address)

    def dry_run(self, step: StepSpec) -> DryRunOutcome:
        msg = self._message_abi(step.function, len(step.args))
        args = self._encode_args_dict(msg.get("args", []), step.args)
        input_data = self.contract.metadata.generate_message_data(
            name=step.function, args=args
        )
        params = encode_contracts_api_call(
            origin=self._keypair(step.sender).public_key,
            dest=bytes.fromhex(ss58_decode(self.address)),
            value=step.value,
            gas_limit=None,
            storage_deposit_limit=None,
            input_data=bytes.fromhex(input_data.to_hex()[2:]),
        )
        try:
            resp = self.substrate.rpc_request(
                "state_call", ["ContractsApi_call", "0x" + params.hex(), None]
            )
            raw = bytes.fromhex(resp["result"][2:])
        except Exception as e:
            return DryRunOutcome("error", error=str(e))
        result = decode_contract_exec_result(raw)
        debug = result["debug_message"] or None
        if "Err" in result["result"]:
            return DryRunOutcome(
                "error", error=result["result"]["Err"]["raw"], debug_message=debug
            )
        ok = result["result"]["Ok"]
        data = bytes.fromhex(ok["data"][2:])
        if ok["flags"] & REVERT_FLAG:
            return DryRunOutcome(
                "revert",
                revert_reason=decode_revert_reason(data),
                return_data_raw=ok["data"],
                debug_message=debug,
            )
        try:
            value = self._decode_return_value(step.function, data)
        except Exception:
            value = None
        return DryRunOutcome(
            "success",
            return_value=value,
            return_data_raw=ok["data"],
            debug_message=debug,
        )

    def transact(self, step: StepSpec) -> TxOutcome:
        msg = self._message_abi(step.function, len(step.args))
        args = self._encode_args_dict(msg.get("args", []), step.args)
        try:
            receipt = self.contract.exec(
                self._keypair(step.sender),
                step.function,
                args=args,
                value=step.value,
                gas_limit=GENEROUS_GAS,
            )
        except Exception as e:
            return TxOutcome("error", error=str(e))
        # any pallet-contracts module failure reverts the contract's state
        status = "success" if receipt.is_success else "revert"
        events = []
        if status == "success":
            try:
                for ce in receipt.contract_events or []:
                    v = ce.value
                    events.append(
                        {
                            "name": v["name"],
                            "args": [
                                {"name": a["label"], "value": norm_value(a["value"])}
                                for a in v["args"]
                            ],
                        }
                    )
            except Exception:
                for e in receipt.triggered_events:
                    if (
                        e.value["module_id"] == "Contracts"
                        and e.value["event_id"] == "ContractEmitted"
                    ):
                        events.append(
                            {
                                "name": None,
                                "args": [],
                                "raw_data": str(
                                    e.value["event"]["attributes"].get("data")
                                ),
                            }
                        )
        gas = None
        for e in receipt.triggered_events or []:
            if e.value.get("event_id") == "ExtrinsicSuccess":
                weight = e.value["event"]["attributes"]["dispatch_info"]["weight"]
                gas = weight["ref_time"]
        return TxOutcome(
            status,
            tx_hash=receipt.extrinsic_hash,
            block_hash=receipt.block_hash,
            gas_used=gas,
            events=events,
            error=None if receipt.is_success else str(receipt.error_message),
        )

    def snapshot(self) -> ChainStateSnapshot:
        number = self.substrate.get_block_number(None)
        block_hash = self.substrate.get_block_hash(number)
        timestamp = self.substrate.query("Timestamp", "Now").value
        account = self.substrate.query("System", "Account", [self.address]).value
        return ChainStateSnapshot(
            chain=self.name,
            block_number=number,
            block_hash=block_hash,
            timestamp=timestamp,
            address=self.address,
            balance=account["data"]["free"],
            nonce=account["nonce"],
            storage=self._contract_storage(),
        )

    def _contract_storage(self) -> dict[str, str] | None:
        try:
            info = self.substrate.query("Contracts", "ContractInfoOf", [self.address])
            if info.value is None:
                return None
            trie_id = bytes.fromhex(info.value["trie_id"][2:])
            child_key = "0x" + (CHILD_STORAGE_PREFIX + trie_id).hex()
            keys = self.substrate.rpc_request(
                "childstate_getKeys", [child_key, "0x", None]
            )
            storage: dict[str, str] = {}
            for key in keys.get("result") or []:
                value = self.substrate.rpc_request(
                    "childstate_getStorage", [child_key, key, None]
                )
                storage[key.lower()] = (value.get("result") or "0x").lower()
            return storage
        except Exception:
            return None
