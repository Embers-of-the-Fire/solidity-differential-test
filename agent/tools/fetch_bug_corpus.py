"""Fetch the raw historical-bug corpus via the GitHub CLI (`gh`).

`gh` handles authentication itself, so this script needs no token plumbing:
it shells out to `gh issue list` / `gh search prs` / `gh api` and caches the
results as raw JSON under `agent/data/bug_corpus/raw/`. The cache is a
committed, reviewable artifact — re-running the fetch refreshes it, and the
distillation stage operates on the cache only (never on the network).

Sources:
  - solang issues labelled `bug` (title/body/url/state)
  - solang merged PRs matching "fix" (title/body/url)
  - solang CHANGELOG.md "Fixed" sections (parsed into entries)
  - solc docs/bugs.json (the EVM-side known-bug catalog)

Usage (from the repo root):
    uv run --package solidity-diff-agent python agent/tools/fetch_bug_corpus.py
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "bug_corpus" / "raw"
SOLANG_REPO = "hyperledger-solang/solang"
SOLC_REPO = "argotorg/solidity"

# gh search prs rejects bodies in --json for some versions; keep the field
# list conservative and identical across calls.
ISSUE_FIELDS = "number,title,body,url,state,labels,createdAt,closedAt"
PR_FIELDS = "number,title,body,url,closedAt"


def gh(args: list[str]) -> str:
    """Run a gh subcommand, returning stdout. Fail fast with context."""
    proc = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(
            f"gh {' '.join(args[:3])} failed (exit {proc.returncode}): "
            f"{proc.stderr.strip()[:300]}"
        )
    return proc.stdout


def gh_json(args: list[str]) -> Any:
    return json.loads(gh(args))


def gh_file_contents(repo: str, path: str) -> str:
    """Download a repo file via `gh api .../contents/<path>` (base64 body)."""
    payload = gh_json(["api", f"repos/{repo}/contents/{path}"])
    assert isinstance(payload, dict)
    return base64.b64decode(str(payload["content"])).decode()


_FIXED_HEADER_RE = re.compile(r"^##\s+\[?(v?[\d][^\]\s]*)\]?", re.MULTILINE)


def parse_changelog_fixed(text: str) -> list[dict[str, str]]:
    """Extract 'Fixed' bullet entries from a keep-a-changelog style file.

    Returns one dict per entry: {version, text}. Versions tag the release the
    fix shipped in (provenance for staleness audits).
    """
    entries: list[dict[str, str]] = []
    version: str | None = None
    in_fixed = False
    for line in text.splitlines():
        m = _FIXED_HEADER_RE.match(line)
        if m:
            version = m.group(1)
            in_fixed = False
            continue
        if line.startswith("### "):
            in_fixed = line[4:].strip().lower() == "fixed"
            continue
        if line.startswith("#"):
            in_fixed = False
            continue
        stripped = line.strip()
        if in_fixed and stripped.startswith("- "):
            entries.append({"version": version or "unreleased", "text": stripped[2:]})
    return entries


def fetch(out_dir: Path, issue_limit: int, pr_limit: int, log) -> dict[str, int]:
    out_dir.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}

    log(f"fetching solang bug issues (limit {issue_limit}) ...")
    issues = gh_json(
        [
            "issue",
            "list",
            "--repo",
            SOLANG_REPO,
            "--label",
            "bug",
            "--state",
            "all",
            "--limit",
            str(issue_limit),
            "--json",
            ISSUE_FIELDS,
        ]
    )
    (out_dir / "solang_issues.json").write_text(json.dumps(issues, indent=2) + "\n")
    counts["solang_issues"] = len(issues)
    time.sleep(1)  # polite pacing between search/API calls

    log(f"fetching solang fix PRs (limit {pr_limit}) ...")
    prs = gh_json(
        [
            "search",
            "prs",
            "--repo",
            SOLANG_REPO,
            "--merged",
            "--limit",
            str(pr_limit),
            "--json",
            PR_FIELDS,
            "fix",
        ]
    )
    (out_dir / "solang_fix_prs.json").write_text(json.dumps(prs, indent=2) + "\n")
    counts["solang_fix_prs"] = len(prs)
    time.sleep(1)

    log("fetching solang CHANGELOG.md ...")
    changelog = gh_file_contents(SOLANG_REPO, "CHANGELOG.md")
    (out_dir / "solang_CHANGELOG.md").write_text(changelog)
    fixed = parse_changelog_fixed(changelog)
    (out_dir / "solang_changelog_fixed.json").write_text(
        json.dumps(fixed, indent=2) + "\n"
    )
    counts["solang_changelog_fixed"] = len(fixed)
    time.sleep(1)

    log("fetching solc docs/bugs.json ...")
    bugs = json.loads(gh_file_contents(SOLC_REPO, "docs/bugs.json"))
    (out_dir / "solc_bugs.json").write_text(json.dumps(bugs, indent=2) + "\n")
    counts["solc_bugs"] = len(bugs)

    meta = {
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "solang_repo": SOLANG_REPO,
        "solc_repo": SOLC_REPO,
        "gh_version": gh(["--version"]).splitlines()[0],
        "counts": counts,
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        metavar="DIR",
        default=str(RAW_DIR),
        help="raw cache directory (default: agent/data/bug_corpus/raw)",
    )
    parser.add_argument("--issue-limit", type=int, default=500)
    parser.add_argument("--pr-limit", type=int, default=300)
    args = parser.parse_args(argv)

    if shutil.which("gh") is None:
        print("error: `gh` CLI not found on PATH", file=sys.stderr)
        return 2
    auth = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
    if auth.returncode != 0:
        print("error: `gh` is not authenticated (run `gh auth login`)", file=sys.stderr)
        return 2

    counts = fetch(Path(args.out), args.issue_limit, args.pr_limit, print)
    print("raw corpus written:", args.out)
    for name, n in counts.items():
        print(f"  {name}: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
