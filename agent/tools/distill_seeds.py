"""Batch-distill the raw bug corpus into candidate seed cards (offline).

Reads the committed raw cache produced by `fetch_bug_corpus.py`, sends one
LLM call per bug report through the agent's validate-and-repair loop, and
writes review-ready candidates:

    candidates/seeds/<id>.json          one candidate seed card per file
    candidates/known_differences.json   Form-B (intentional difference) candidates
    candidates/skipped.json             reports the model judged out of scope
    candidates/index.json               deterministic pre-review ranking

A human gate then copies accepted seed cards into `agent/seeds_derived/`
(the frozen corpus) and appends accepted known-differences to
`agent/src/agent/data/known_differences.json`.

Usage (from the repo root; LLM endpoint via AGENT_LLM_* env vars):
    uv run --package solidity-diff-agent python agent/tools/distill_seeds.py
    ... --dry-run            # list corpus records, no LLM calls
    ... --limit 10           # distill the first 10 records only
    ... --only solang-issue-777,solc-bugs-SOL-2023-1
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from agent.config import load_config
from agent.llm import LLMClient, LLMError
from agent.prompts import load_prompt

AGENT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = AGENT_ROOT / "data" / "bug_corpus" / "raw"
CANDIDATES_DIR = AGENT_ROOT / "data" / "bug_corpus" / "candidates"

MAX_BODY_CHARS = 4000
KEBAB_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

# Deterministic pre-review ranking: features of the *raw report* that
# correlate with a generalizable codegen-semantics pattern (as opposed to a
# crash, tooling issue or platform-specific fix).
_RANK_KEYWORDS = (
    "overflow",
    "underflow",
    "constant fold",
    "constant-fold",
    "shift",
    "cast",
    "abi",
    "encod",
    "decod",
    "sign",
    "division",
    "modulo",
    "keccak",
    "hash",
    "storage",
    "array",
    "mapping",
    "revert",
    "panic",
    "optimizer",
    "codegen",
    "incorrect",
    "wrong",
)


def load_corpus(raw_dir: Path) -> list[dict[str, Any]]:
    """Unify the raw cache files into flat bug records.

    Each record: {ref, kind, title, body, url, fixed_in}.
    """
    records: list[dict[str, Any]] = []

    issues_path = raw_dir / "solang_issues.json"
    if issues_path.exists():
        for issue in json.loads(issues_path.read_text()):
            records.append(
                {
                    "ref": f"solang-issue-{issue['number']}",
                    "kind": "solang-issue",
                    "title": issue["title"],
                    "body": issue.get("body") or "",
                    "url": issue["url"],
                    "fixed_in": None,
                }
            )

    prs_path = raw_dir / "solang_fix_prs.json"
    if prs_path.exists():
        for pr in json.loads(prs_path.read_text()):
            records.append(
                {
                    "ref": f"solang-pr-{pr['number']}",
                    "kind": "solang-pr",
                    "title": pr["title"],
                    "body": pr.get("body") or "",
                    "url": pr["url"],
                    "fixed_in": None,
                }
            )

    changelog_path = raw_dir / "solang_changelog_fixed.json"
    if changelog_path.exists():
        for i, entry in enumerate(json.loads(changelog_path.read_text())):
            records.append(
                {
                    "ref": f"solang-changelog-{i}",
                    "kind": "solang-changelog",
                    "title": entry["text"][:120],
                    "body": entry["text"],
                    "url": "https://github.com/hyperledger-solang/solang/blob/main/CHANGELOG.md",
                    "fixed_in": entry.get("version"),
                }
            )

    solc_path = raw_dir / "solc_bugs.json"
    if solc_path.exists():
        for bug in json.loads(solc_path.read_text()):
            body = "\n\n".join(
                part for part in (bug.get("summary"), bug.get("description")) if part
            )
            records.append(
                {
                    "ref": f"solc-bugs-{bug.get('uid', len(records))}",
                    "kind": "solc-bugs",
                    "title": bug.get("name", "(unnamed)"),
                    "body": body,
                    "url": "https://github.com/argotorg/solidity/blob/develop/docs/bugs.json",
                    "fixed_in": bug.get("fixed"),
                }
            )

    return records


def rank_score(record: dict[str, Any]) -> int:
    """Deterministic pre-review score; higher = review earlier."""
    text = f"{record['title']}\n{record['body']}".lower()
    score = 0
    for kw in _RANK_KEYWORDS:
        if kw in text:
            score += 1
    if "```" in record["body"]:  # report contains a code reproducer
        score += 3
    if record["kind"] == "solang-changelog":
        score += 2  # changelog entries are pre-filtered bug summaries
    if record["fixed_in"]:
        score += 1
    return score


def validate_distillation(d: dict[str, Any]) -> list[str]:
    """Validate one model reply (Form A seed / Form B known-diff / Form C skip)."""
    kind = d.get("kind")
    if kind == "skip":
        if not isinstance(d.get("reason"), str) or not d["reason"]:
            return ["'reason' must be a non-empty string"]
        return []
    if kind == "seed":
        problems = []
        if not isinstance(d.get("id"), str) or not KEBAB_RE.match(d["id"]):
            problems.append("'id' must be kebab-case")
        if not isinstance(d.get("title"), str) or not d["title"]:
            problems.append("'title' must be a non-empty string")
        why = d.get("why")
        if not isinstance(why, str) or not why:
            problems.append("'why' must be a non-empty string")
        elif "solc" not in why.lower() or "solang" not in why.lower():
            problems.append(
                "'why' must state a cross-implementation divergence hypothesis "
                "mentioning both solc and solang"
            )
        hints = d.get("hints")
        if (
            not isinstance(hints, list)
            or not hints
            or not all(isinstance(h, str) and h for h in hints)
        ):
            problems.append("'hints' must be a non-empty array of strings")
        source = d.get("source")
        if (
            not isinstance(source, dict)
            or not isinstance(source.get("url"), str)
            or not isinstance(source.get("kind"), str)
        ):
            problems.append("'source' must be an object with 'kind' and 'url'")
        return problems
    if kind == "known_difference":
        problems = []
        if not isinstance(d.get("id"), str) or not KEBAB_RE.match(d["id"]):
            problems.append("'id' must be kebab-case")
        markers = d.get("source_markers")
        if not isinstance(markers, list) or not all(
            isinstance(m, str) for m in markers
        ):
            problems.append("'source_markers' must be an array of strings")
        if not isinstance(d.get("rationale"), str) or not d["rationale"]:
            problems.append("'rationale' must be a non-empty string")
        return problems
    return ["'kind' must be 'seed', 'known_difference' or 'skip'"]


def build_prompt(template, record: dict[str, Any]) -> tuple[str, str]:
    body = record["body"]
    if len(body) > MAX_BODY_CHARS:
        body = body[:MAX_BODY_CHARS] + "\n... (truncated)"
    user = template.substitute(
        kind=record["kind"], url=record["url"], title=record["title"], body=body
    )
    system = (
        "You distill historical compiler bug reports into differential-testing "
        "seed cards. You reply with a single JSON object and nothing else."
    )
    return system, user


def distill(
    client,
    records: list[dict[str, Any]],
    out_dir: Path,
    log,
) -> dict[str, int]:
    template = load_prompt("distill_seed")
    seeds_dir = out_dir / "seeds"
    seeds_dir.mkdir(parents=True, exist_ok=True)
    known_differences: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    index: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    counts = {"seed": 0, "known_difference": 0, "skip": 0, "error": 0}

    for record in records:
        log(f"[distill] {record['ref']}: {record['title'][:80]}")
        system, user = build_prompt(template, record)
        try:
            reply = client.chat_json(
                system, user, validate=validate_distillation, stage="distill"
            )
        except LLMError as e:
            log(f"  -> error: {e}")
            counts["error"] += 1
            continue

        kind = reply["kind"]
        counts[kind] += 1
        if kind == "skip":
            skipped.append({"ref": record["ref"], "reason": reply["reason"]})
            continue
        if kind == "known_difference":
            reply["provenance"] = {"ref": record["ref"], "url": record["url"]}
            known_differences.append(reply)
            continue

        card_id = reply["id"]
        if card_id in used_ids:
            card_id = f"{card_id}-{record['ref'].rsplit('-', 1)[-1]}"
            reply["id"] = card_id
        used_ids.add(card_id)
        reply.setdefault("source", {})
        reply["source"].setdefault("kind", record["kind"])
        reply["source"].setdefault("url", record["url"])
        reply["source"].setdefault("fixed_in", record["fixed_in"])
        (seeds_dir / f"{card_id}.json").write_text(json.dumps(reply, indent=2) + "\n")
        index.append(
            {
                "id": card_id,
                "ref": record["ref"],
                "title": reply["title"],
                "url": record["url"],
                "score": rank_score(record),
            }
        )

    index.sort(key=lambda e: (-e["score"], e["id"]))
    (out_dir / "known_differences.json").write_text(
        json.dumps(known_differences, indent=2) + "\n"
    )
    (out_dir / "skipped.json").write_text(json.dumps(skipped, indent=2) + "\n")
    (out_dir / "index.json").write_text(json.dumps(index, indent=2) + "\n")
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", metavar="DIR", default=str(RAW_DIR))
    parser.add_argument("--out", metavar="DIR", default=str(CANDIDATES_DIR))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--only", metavar="REFS", default=None)
    parser.add_argument(
        "--findings-dir",
        metavar="DIR",
        default="findings",
        help="where llm_usage.jsonl is appended (default: findings/)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="list corpus records, no LLM calls"
    )
    args = parser.parse_args(argv)

    raw_dir = Path(args.raw)
    if not raw_dir.is_dir():
        print(f"error: raw cache not found: {raw_dir}", file=sys.stderr)
        print("run agent/tools/fetch_bug_corpus.py first", file=sys.stderr)
        return 2
    records = load_corpus(raw_dir)
    if not records:
        print(f"error: no bug records in {raw_dir}", file=sys.stderr)
        return 2

    # Pre-review ranking order: the --limit subset then covers the most
    # promising reports first.
    records.sort(key=lambda r: (-rank_score(r), r["ref"]))
    if args.only:
        wanted = set(args.only.split(","))
        records = [r for r in records if r["ref"] in wanted]
    if args.limit is not None:
        records = records[: args.limit]

    if args.dry_run:
        print(f"{len(records)} record(s):")
        for r in records:
            print(f"  [{rank_score(r):2d}] {r['ref']:<24} {r['title'][:70]}")
        return 0

    cfg = load_config(findings_dir=args.findings_dir)
    cfg.llm_calls_budget = max(cfg.llm_calls_budget, 4 * len(records))
    client = LLMClient(cfg)
    counts = distill(client, records, Path(args.out), print)
    totals = client.usage_totals()["totals"]
    print(
        f"distilled {len(records)} record(s): {counts['seed']} seed candidate(s), "
        f"{counts['known_difference']} known-difference, {counts['skip']} skipped, "
        f"{counts['error']} error(s)"
    )
    print(
        f"llm: {totals['calls']} calls, {totals['total_tokens']} tokens, "
        f"${totals['cost_usd']:.6f}"
    )
    print(f"candidates written to {args.out}; review, then copy accepted cards")
    print("to agent/seeds_derived/ and known-differences to")
    print("agent/src/agent/data/known_differences.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
