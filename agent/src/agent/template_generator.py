"""Deterministic, LLM-free Solidity probe generation from language templates.

The templates intentionally use small, commonplace Solidity constructs that both
solc and solang can parse.  Randomness is limited to values, expressions, and
transaction schedules; all random choices come from the caller-supplied RNG.
"""

from __future__ import annotations

import random
from typing import Any

from .seeds import Seed

SUPPORTED_SEED_IDS = (
    "contract_structure",
    "control_flow",
    "crypto_builtins",
    "env_vars",
    "events",
    "int_semantics",
    "revert_reasons",
    "storage_layout",
    "strings_bytes",
    "value_transfers",
)

_UINT256_MAX = 2**256 - 1
_INT256_MIN = -(2**255)
_INT256_MAX = 2**255 - 1
_SMALL_UINTS = (0, 1, 2, 7, 15, 16, 31, 32, 255, 256)
_UINT_BOUNDARIES = _SMALL_UINTS + (
    65_535,
    65_536,
    2**32 - 1,
    2**32,
    _UINT256_MAX - 1,
    _UINT256_MAX,
)
_INT_BOUNDARIES = (
    _INT256_MIN,
    _INT256_MIN + 1,
    -65_537,
    -65_536,
    -257,
    -256,
    -255,
    -8,
    -7,
    -2,
    -1,
    0,
    1,
    2,
    7,
    8,
    255,
    256,
    _INT256_MAX,
)
_SENDERS = ("deployer", "alice", "bob", "charlie")
_PRAGMA = "// SPDX-License-Identifier: MIT\npragma solidity >=0.8.0;\n\n"


def _step(
    action: str,
    function: str,
    args: list[Any] | None = None,
    *,
    sender: str = "deployer",
    value: int = 0,
) -> dict[str, Any]:
    return {
        "action": action,
        "function": function,
        "args": list(args or []),
        "sender": sender,
        "value": value,
    }


def _spec(
    seed_id: str,
    variant: str,
    contract: str,
    source: str,
    steps: list[dict[str, Any]],
    constructor_args: list[Any] | None = None,
) -> dict[str, Any]:
    return {
        "name": f"template-{seed_id.replace('_', '-')}-{variant}",
        "solidity": _PRAGMA + source.strip() + "\n",
        "contract": contract,
        "constructor": {"args": list(constructor_args or [])},
        "oracle": {
            "storage": "count",
            "events": True,
            "revert_reasons": True,
            "gas": False,
        },
        "execution": "on-chain",
        "steps": steps,
    }


def _contract_structure(rng: random.Random) -> dict[str, Any]:
    initial = rng.choice(_SMALL_UINTS)
    argument = rng.choice(_SMALL_UINTS)
    replacement = rng.choice(_SMALL_UINTS)
    multiplier = rng.choice((1, 2, 3, 5))
    increment = rng.choice((0, 1, 3, 7))
    source = f"""contract StructureBase {{
    uint256 internal baseValue;

    constructor(uint256 initial) {{
        baseValue = initial;
    }}

    function describe(uint256 value) public view virtual returns (uint256) {{
        return baseValue + value;
    }}
}}

contract StructureProbe is StructureBase {{
    constructor(uint256 initial) StructureBase(initial) {{}}

    function describe(uint256 value) public view override returns (uint256) {{
        return baseValue * {multiplier} + value + {increment};
    }}

    function update(uint256 value) public {{
        baseValue = value;
    }}

    function current() public view returns (uint256) {{
        return baseValue;
    }}
}}"""
    steps = [
        _step("query", "describe", [argument]),
        _step("call", "update", [replacement], sender=rng.choice(_SENDERS)),
        _step("query", "describe", [argument]),
        _step("query", "current"),
    ]
    return _spec(
        "contract_structure",
        "inheritance",
        "StructureProbe",
        source,
        steps,
        [initial],
    )


def _control_flow(rng: random.Random) -> dict[str, Any]:
    first = rng.choice((0, 1, 2, 7, 8, 9, 255, _UINT256_MAX))
    second = rng.choice((0, 1, 2, 3, 8, 9))
    multiplier = rng.choice((1, 2, 3))
    increment = rng.choice((0, 1, 2))
    skip = rng.choice((1, 2, 3))
    source = f"""contract ControlFlowProbe {{
    uint256 private total;
    uint256 private visits;

    function run(uint256 n) public returns (uint256) {{
        if (n > 8) {{
            n = 8;
        }}
        for (uint256 i = 0; i < n; i++) {{
            if (i == {skip}) {{
                continue;
            }}
            if (i == 7) {{
                break;
            }}
            total += i * {multiplier} + {increment};
            visits += 1;
        }}
        return total;
    }}

    function summary() public view returns (uint256, uint256) {{
        return (total, visits);
    }}
}}"""
    steps = [
        _step("call", "run", [first], sender=rng.choice(_SENDERS)),
        _step("query", "summary"),
        _step("call", "run", [second], sender=rng.choice(_SENDERS)),
        _step("query", "summary"),
    ]
    return _spec("control_flow", "bounded-loop", "ControlFlowProbe", source, steps)


def _crypto_builtins(rng: random.Random) -> dict[str, Any]:
    salt = rng.choice((1, 7, 17, 255, 256))
    first_value = rng.choice(_UINT_BOUNDARIES)
    second_value = rng.choice(_UINT_BOUNDARIES)
    first_text = rng.choice(("", "a", "solidity", "x" * 31, "x" * 32))
    second_text = rng.choice(("", "b", "template", "y" * 33))
    encoder = rng.choice(("abi.encodePacked", "abi.encode"))
    source = f"""contract CryptoProbe {{
    bytes32 private last;
    uint256 private constant SALT = {salt};

    function preview(uint256 value, string memory text)
        public
        pure
        returns (bytes32)
    {{
        return keccak256({encoder}(value, text, SALT));
    }}

    function record(uint256 value, string memory text) public returns (bytes32) {{
        last = preview(value, text);
        return last;
    }}

    function current() public view returns (bytes32) {{
        return last;
    }}
}}"""
    steps = [
        _step("query", "preview", [first_value, first_text]),
        _step(
            "call",
            "record",
            [second_value, second_text],
            sender=rng.choice(_SENDERS),
        ),
        _step("query", "current"),
    ]
    return _spec("crypto_builtins", "keccak", "CryptoProbe", source, steps)


def _env_vars(rng: random.Random) -> dict[str, Any]:
    expression = rng.choice(
        (
            "block.number",
            "block.timestamp",
            "block.number + block.timestamp",
            "block.number * 2 + block.timestamp",
        )
    )
    source = f"""contract EnvProbe {{
    uint256 private saved;
    address private caller;

    function observe() public view returns (uint256) {{
        return {expression};
    }}

    function capture() public returns (uint256) {{
        saved = {expression};
        caller = msg.sender;
        return saved;
    }}

    function snapshot() public view returns (uint256, address) {{
        return (saved, caller);
    }}
}}"""
    steps = [
        _step("query", "observe"),
        _step("call", "capture", sender=rng.choice(_SENDERS)),
        _step("query", "snapshot"),
        _step("query", "observe"),
    ]
    return _spec("env_vars", "block-context", "EnvProbe", source, steps)


def _events(rng: random.Random) -> dict[str, Any]:
    first_value = rng.choice(_UINT_BOUNDARIES)
    second_value = rng.choice(_SMALL_UINTS)
    first_note = rng.choice(("", "first", "x" * 32))
    second_note = rng.choice(("", "second", "event"))
    duplicate = rng.choice((True, False))
    duplicate_emit = "\n        emit Marker(value);" if duplicate else ""
    source = f"""contract EventsProbe {{
    event Recorded(address indexed sender, uint256 indexed value, string note);
    event Marker(uint256 indexed sequence);

    uint256 private count;

    function publish(uint256 value, string memory note) public {{
        count += 1;
        emit Recorded(msg.sender, value, note);
        emit Marker(count);{duplicate_emit}
    }}

    function total() public view returns (uint256) {{
        return count;
    }}
}}"""
    steps = [
        _step(
            "call",
            "publish",
            [first_value, first_note],
            sender=rng.choice(_SENDERS),
        ),
        _step("query", "total"),
        _step(
            "call",
            "publish",
            [second_value, second_note],
            sender=rng.choice(_SENDERS),
        ),
        _step("query", "total"),
    ]
    variant = "ordered-duplicate" if duplicate else "ordered-events"
    return _spec("events", variant, "EventsProbe", source, steps)


def _int_semantics(rng: random.Random) -> dict[str, Any]:
    operation = rng.choice(("division", "modulo", "shift", "narrow-cast"))
    if operation in ("division", "modulo"):
        divisor = rng.choice((2, 3, 7, -2, -3))
        operator = "/" if operation == "division" else "%"
        expression = f"value {operator} ({divisor})"
    elif operation == "shift":
        expression = f"value >> {rng.choice((1, 2, 7))}"
    else:
        expression = "int256(int8(value))"
    first = rng.choice(_INT_BOUNDARIES)
    second = rng.choice(_INT_BOUNDARIES)
    source = f"""contract IntProbe {{
    int256 private last;

    function preview(int256 value) public pure returns (int256) {{
        return {expression};
    }}

    function record(int256 value) public returns (int256) {{
        last = preview(value);
        return last;
    }}

    function current() public view returns (int256) {{
        return last;
    }}
}}"""
    steps = [
        _step("query", "preview", [first]),
        _step("call", "record", [second], sender=rng.choice(_SENDERS)),
        _step("query", "current"),
    ]
    return _spec("int_semantics", operation, "IntProbe", source, steps)


def _revert_reasons(rng: random.Random) -> dict[str, Any]:
    mode = rng.choice(("require", "revert", "assert"))
    forbidden = rng.choice((0, 1, 2, 255, 256))
    allowed = rng.choice(tuple(v for v in _UINT_BOUNDARIES if v != forbidden))
    divisor = rng.choice((1, 2, 3, 7))
    if mode == "require":
        guard = f'require(value != {forbidden}, "boundary rejected");'
    elif mode == "revert":
        guard = (
            f"if (value == {forbidden}) {{\n"
            '            revert("boundary rejected");\n'
            "        }"
        )
    else:
        guard = f"assert(value != {forbidden});"
    source = f"""contract RevertProbe {{
    uint256 private accepted;

    function check(uint256 value) public returns (uint256) {{
        {guard}
        accepted = value / {divisor};
        return accepted;
    }}

    function current() public view returns (uint256) {{
        return accepted;
    }}
}}"""
    steps = [
        _step("call", "check", [forbidden], sender=rng.choice(_SENDERS)),
        _step("call", "check", [allowed], sender=rng.choice(_SENDERS)),
        _step("query", "current"),
    ]
    return _spec("revert_reasons", mode, "RevertProbe", source, steps)


def _storage_layout(rng: random.Random) -> dict[str, Any]:
    key = rng.choice((0, 1, 127, 128, 254, 255))
    value = rng.choice(_UINT_BOUNDARIES)
    assignments = [
        "small = key;",
        "medium = uint16(value);",
        "flag = value % 2 == 1;",
        "values[key] = value;",
    ]
    rng.shuffle(assignments)
    writes = "\n        ".join(assignments)
    source = f"""contract StorageProbe {{
    uint8 private small;
    uint16 private medium;
    bool private flag;
    mapping(uint8 => uint256) private values;

    function write(uint8 key, uint256 value) public {{
        {writes}
    }}

    function clear(uint8 key) public {{
        delete values[key];
        small = 0;
        flag = false;
    }}

    function packed() public view returns (uint8, uint16, bool) {{
        return (small, medium, flag);
    }}

    function read(uint8 key) public view returns (uint256) {{
        return values[key];
    }}
}}"""
    steps = [
        _step("call", "write", [key, value], sender=rng.choice(_SENDERS)),
        _step("query", "packed"),
        _step("query", "read", [key]),
        _step("call", "clear", [key], sender=rng.choice(_SENDERS)),
        _step("query", "packed"),
        _step("query", "read", [key]),
    ]
    return _spec("storage_layout", "packed-delete", "StorageProbe", source, steps)


def _strings_bytes(rng: random.Random) -> dict[str, Any]:
    first_length = rng.choice((0, 1, 31, 32, 33))
    second_length = rng.choice((0, 1, 31, 32, 33))
    byte_length = rng.choice((0, 1, 31, 32, 33))
    first = "x" * first_length
    second = "y" * second_length
    byte_value = "0x" + "ab" * byte_length
    source = """contract StringsProbe {
    string private saved;

    function store(string memory value) public {
        saved = value;
    }

    function read() public view returns (string memory) {
        return saved;
    }

    function size(string memory value) public pure returns (uint256) {
        return bytes(value).length;
    }

    function byteSize(bytes memory value) public pure returns (uint256) {
        return value.length;
    }
}"""
    steps = [
        _step("query", "size", [first]),
        _step("query", "byteSize", [byte_value]),
        _step("call", "store", [first], sender=rng.choice(_SENDERS)),
        _step("query", "read"),
        _step("call", "store", [second], sender=rng.choice(_SENDERS)),
        _step("query", "read"),
    ]
    return _spec("strings_bytes", "lengths", "StringsProbe", source, steps)


def _value_transfers(rng: random.Random) -> dict[str, Any]:
    amounts = (0, 1, 2, 10, 1_000, 1_000_000, 1_000_000_000_000)
    first = rng.choice(amounts)
    second = rng.choice(amounts)
    plain_value = rng.choice((0, 1))
    source = """contract ValueProbe {
    uint256 private received;
    uint256 private calls;

    function deposit() public payable returns (uint256) {
        received += msg.value;
        calls += 1;
        return msg.value;
    }

    function plain() public {
        calls += 1;
    }

    function totals() public view returns (uint256, uint256) {
        return (received, calls);
    }

    function contractBalance() public view returns (uint256) {
        return address(this).balance;
    }
}"""
    steps = [
        _step("call", "deposit", sender=rng.choice(("alice", "bob")), value=first),
        _step("query", "totals"),
        _step(
            "call",
            "plain",
            sender=rng.choice(("alice", "bob")),
            value=plain_value,
        ),
        _step("call", "deposit", sender=rng.choice(("alice", "bob")), value=second),
        _step("query", "contractBalance"),
        _step("query", "totals"),
    ]
    return _spec("value_transfers", "payable", "ValueProbe", source, steps)


_BUILDERS = {
    "contract_structure": _contract_structure,
    "control_flow": _control_flow,
    "crypto_builtins": _crypto_builtins,
    "env_vars": _env_vars,
    "events": _events,
    "int_semantics": _int_semantics,
    "revert_reasons": _revert_reasons,
    "storage_layout": _storage_layout,
    "strings_bytes": _strings_bytes,
    "value_transfers": _value_transfers,
}


def _seed_id(seed: Seed | dict[str, Any] | str) -> str:
    if isinstance(seed, str):
        raw_id = seed
    elif isinstance(seed, dict):
        raw_id = seed.get("id")
    else:
        raw_id = getattr(seed, "id", None)
    if not isinstance(raw_id, str) or not raw_id:
        raise ValueError("seed must be a seed ID or an object with a string 'id'")
    return raw_id.replace("-", "_")


def generate_template_spec(
    seed: Seed | dict[str, Any] | str,
    rng: random.Random,
    recent_probes: list[dict] | None = None,
    notebook: dict | None = None,
) -> dict:
    """Return a fresh oracle spec generated without an LLM.

    ``recent_probes`` and ``notebook`` are accepted for drop-in compatibility
    with history-aware generators.  Templates intentionally ignore them so the
    same seed and RNG state always produce the same result.  Packaged kebab-case
    seed IDs and their underscore spellings are equivalent.
    """
    del recent_probes, notebook
    seed_id = _seed_id(seed)
    builder = _BUILDERS.get(seed_id)
    if builder is None:
        supported = ", ".join(SUPPORTED_SEED_IDS)
        raise ValueError(
            f"unsupported template seed {seed_id!r}; expected: {supported}"
        )
    return builder(rng)
