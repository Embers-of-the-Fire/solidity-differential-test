"""Report rendering: JSON (machine-readable) and Markdown (human-readable)."""

from __future__ import annotations

from typing import Any

from .schema import dumps


def write_json(report: dict[str, Any], path: str) -> None:
    with open(path, "w") as f:
        f.write(dumps(report, indent=2))
        f.write("\n")


def render_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = []
    verdict = report["verdict"]
    lines.append(f"# Differential Oracle Report: {report['name']}")
    lines.append("")
    lines.append(f"**Verdict: {verdict}**")
    lines.append("")
    lines.append(f"- Contract: `{report['contract']}`")
    lines.append(f"- solc: {report['tool_versions'].get('solc', '?')}")
    lines.append(f"- solang: {report['tool_versions'].get('solang', '?')}")
    lines.append(f"- anvil: {report['tool_versions'].get('anvil', '?')}")
    lines.append(
        f"- substrate-contracts-node: {report['tool_versions'].get('substrate-contracts-node', '?')}"
    )
    cfg = report.get("oracle_config", {})
    lines.append(
        f"- Oracle config: storage=`{cfg.get('storage')}`, events={cfg.get('events')}, "
        f"revert_reasons={cfg.get('revert_reasons')}, gas={cfg.get('gas')}"
    )
    lines.append("")

    # compile stage
    lines.append("## Compile stage")
    lines.append("")
    lines.append("| Compiler | OK | Errors |")
    lines.append("|----------|----|--------|")
    for name, c in report.get("compile", {}).items():
        errs = "; ".join((c.get("errors") or [])[:1])
        lines.append(f"| {name} | {c.get('ok')} | {errs[:200]} |")
    lines.append("")

    # deploy stage
    if report.get("deploy"):
        lines.append("## Deploy stage")
        lines.append("")
        lines.append("| Chain | Status | Address | Error |")
        lines.append("|-------|--------|---------|-------|")
        for name, d in report["deploy"].items():
            lines.append(
                f"| {name} | {d.get('status')} | `{d.get('address')}` | {(d.get('error') or '')[:120]} |"
            )
        lines.append("")

    # steps
    if report.get("steps"):
        lines.append("## Steps")
        lines.append("")
        lines.append(
            "| # | Action | Function | EVM status | DOT status | EVM return | DOT return | Divergences |"
        )
        lines.append(
            "|---|--------|----------|------------|------------|------------|------------|-------------|"
        )
        for s in report["steps"]:
            evm = s.get("evm", {})
            dot = s.get("polkadot", {})
            evm_status = (evm.get("tx") or evm.get("dry_run", {})).get("status")
            dot_status = (dot.get("tx") or dot.get("dry_run", {})).get("status")
            evm_ret = _short(evm.get("dry_run", {}).get("return_value"))
            dot_ret = _short(dot.get("dry_run", {}).get("return_value"))
            kinds = ", ".join(d["kind"] for d in s.get("divergences", [])) or "-"
            lines.append(
                f"| {s['index']} | {s['action']} | `{s['function']}` | {evm_status} | {dot_status} "
                f"| {evm_ret} | {dot_ret} | {kinds} |"
            )
        lines.append("")

    # divergences
    lines.append("## Divergences")
    lines.append("")
    if report.get("divergences"):
        for d in report["divergences"]:
            step = f"step {d['step']}" if d["step"] is not None else "setup"
            lines.append(f"- **{d['kind']}** ({step}): {d['detail']}")
            lines.append(f"  - evm: `{dumps(d.get('evm'))[:400]}`")
            lines.append(f"  - polkadot: `{dumps(d.get('polkadot'))[:400]}`")
    else:
        lines.append("None.")
    lines.append("")
    return "\n".join(lines)


def _short(v: Any) -> str:
    s = dumps(v)
    return s if len(s) <= 40 else s[:37] + "..."


def write_markdown(report: dict[str, Any], path: str) -> None:
    with open(path, "w") as f:
        f.write(render_markdown(report))
