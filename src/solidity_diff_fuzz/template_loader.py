from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined


def build_environment(root_dir: Path) -> Environment:
    templates_dir = root_dir / "templates"
    return Environment(
        loader=FileSystemLoader(templates_dir),
        autoescape=False,
        keep_trailing_newline=True,
        lstrip_blocks=True,
        trim_blocks=True,
        undefined=StrictUndefined,
    )


def render_template(
    environment: Environment, template_name: str, **context: object
) -> str:
    return environment.get_template(template_name).render(**context)
