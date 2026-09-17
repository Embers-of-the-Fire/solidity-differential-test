"""Prompt template loading (string.Template; `$var` slots)."""

from __future__ import annotations

from importlib.resources import files
from string import Template


def load_prompt(name: str) -> Template:
    text = (files("agent") / "prompts" / f"{name}.md").read_text()
    return Template(text)
