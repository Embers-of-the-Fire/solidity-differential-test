"""Well-known account labels shared by both chains.

Spec arguments and decoded return/event values may reference accounts by label
using the ``$name`` convention (e.g. ``$alice``). Each chain adapter resolves
labels to its native address format; decoded values are reverse-mapped back to
labels so address values compare equal across chains.
"""

from __future__ import annotations

from dataclasses import dataclass

# anvil default dev accounts (account 0 = deployer)
ANVIL_ACCOUNTS = [
    (
        "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266",
        "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80",
    ),
    (
        "0x70997970C51812dc3A010C7d01b50e0d17dc79C8",
        "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d",
    ),
    (
        "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC",
        "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a",
    ),
    (
        "0x90F79bf6EB2c4f870365E785982E1f101E93b906",
        "0x7c852118294e51e653712a81e05800f419141751be58f605c371e15141b007a6",
    ),
]

SUBSTRATE_URIS = ["//Alice", "//Bob", "//Charlie", "//Dave"]

LABELS = ["deployer", "alice", "bob", "charlie"]


@dataclass
class Account:
    label: str
    evm_address: str
    evm_key: str
    substrate_uri: str
    ss58_address: str = ""  # filled by the polkadot adapter at startup


def default_accounts() -> dict[str, Account]:
    return {
        label: Account(
            label=label,
            evm_address=ANVIL_ACCOUNTS[i][0],
            evm_key=ANVIL_ACCOUNTS[i][1],
            substrate_uri=SUBSTRATE_URIS[i],
        )
        for i, label in enumerate(LABELS)
    }


class LabelResolver:
    """Bidirectional label <-> native address mapping, per chain."""

    def __init__(self, accounts: dict[str, Account]):
        self.accounts = accounts
        self._evm_to_label = {
            a.evm_address.lower(): f"${label}" for label, a in accounts.items()
        }
        self._ss58_to_label: dict[str, str] = {}
        self._contract_labels: dict[
            str, str
        ] = {}  # native address (lower) -> $contract

    def register_ss58(self, label: str, ss58: str) -> None:
        self._ss58_to_label[ss58] = f"${label}"

    def register_contract(self, evm_address: str, ss58_address: str) -> None:
        self._contract_labels[evm_address.lower()] = "$contract"
        self._contract_labels[ss58_address] = "$contract"

    def is_label(self, value) -> bool:
        return isinstance(value, str) and value.startswith("$")

    def evm_address(self, value: str) -> str:
        label = value[1:]
        if label == "contract":
            return "$contract"  # resolved by adapter (needs deployed address)
        return self.accounts[label].evm_address

    def substrate_uri(self, label: str) -> str:
        return self.accounts[label].substrate_uri

    def relabel(self, value):
        """Replace known native addresses in decoded values with $labels."""
        if isinstance(value, str):
            if value.lower() in self._evm_to_label:
                return self._evm_to_label[value.lower()]
            if value.lower() in self._contract_labels:
                return "$contract"
            if value in self._ss58_to_label:
                return self._ss58_to_label[value]
            if value in self._contract_labels:
                return "$contract"
            return value
        if isinstance(value, list):
            return [self.relabel(v) for v in value]
        if isinstance(value, tuple):
            return [self.relabel(v) for v in value]
        if isinstance(value, dict):
            return {k: self.relabel(v) for k, v in value.items()}
        return value
