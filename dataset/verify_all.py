"""Replay every exported witness and assert its signature matches.

Exit 0 iff every witnesses/*/spec.min.json replays to DIVERGENCE with the
earliest signature recorded in signature.json. Run inside the devshell:

    uv run python dataset/verify_all.py
"""

import json
import sys
from pathlib import Path

from agent.executor import earliest_signature, run_spec_dict


def main() -> int:
    root = Path(__file__).parent / "witnesses"
    failures = 0
    for witness in sorted(root.iterdir()):
        if not witness.is_dir():
            continue
        spec = json.loads((witness / "spec.min.json").read_text())
        expected = json.loads((witness / "signature.json").read_text())[
            "earliest_signature"
        ]
        report = run_spec_dict(spec)
        actual = earliest_signature(report)
        ok = report.get("verdict") == "DIVERGENCE" and actual == expected
        print(f"{witness.name}: {'OK' if ok else 'MISMATCH'} ({actual})")
        if not ok:
            failures += 1
    print(f"{failures} mismatch(es)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
