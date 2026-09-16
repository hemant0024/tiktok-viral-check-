"""Prompt loader. Prompt text lives in prompts/*.md, never in Python."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from ci.config import PROMPTS_DIR

_HEADER = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
_SCHEMA_BLOCK = re.compile(r"```json schema\n(.*?)\n```", re.DOTALL)


@dataclass
class Prompt:
    name: str
    version: str
    tier: str
    description: str
    template: str
    schema: dict

    def render(self, **kwargs) -> str:
        out = self.template
        for key, value in kwargs.items():
            token = "{{" + key + "}}"
            if token in out:
                rendered = value if isinstance(value, str) else json.dumps(value, indent=2, default=str)
                out = out.replace(token, rendered)
        return out


def _parse_header(text: str) -> dict[str, str]:
    match = _HEADER.match(text)
    if not match:
        raise ValueError("prompt file is missing its --- version header ---")
    meta = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta


def load_prompt(name: str, prompts_dir: Path | None = None) -> Prompt:
    directory = Path(prompts_dir or PROMPTS_DIR)
    matches = sorted(directory.glob(f"*{name}.md"))
    if not matches:
        raise FileNotFoundError(f"no prompt file matching '{name}' in {directory}")
    text = matches[0].read_text()
    meta = _parse_header(text)
    body = _HEADER.sub("", text, count=1)
    schema_match = _SCHEMA_BLOCK.search(body)
    if not schema_match:
        raise ValueError(f"prompt '{name}' has no ```json schema``` block")
    schema = json.loads(schema_match.group(1))
    template = _SCHEMA_BLOCK.sub("", body).strip()
    return Prompt(
        name=meta.get("name", name),
        version=meta.get("version", "0"),
        tier=meta.get("tier", "cheap"),
        description=meta.get("description", ""),
        template=template,
        schema=schema,
    )


def validate_against_schema(payload: dict, schema: dict) -> list[str]:
    """Minimal structural validation. Deliberately dependency free."""
    errors: list[str] = []
    for field in schema.get("required", []):
        if field not in payload:
            errors.append(f"missing required field: {field}")
    props = schema.get("properties", {})
    type_map = {
        "string": str, "number": (int, float), "integer": int,
        "boolean": bool, "array": list, "object": dict,
    }
    for field, spec in props.items():
        if field not in payload:
            continue
        expected = spec.get("type")
        if expected and expected in type_map and not isinstance(payload[field], type_map[expected]):
            errors.append(f"{field}: expected {expected}, got {type(payload[field]).__name__}")
        enum = spec.get("enum")
        if enum and payload[field] not in enum:
            errors.append(f"{field}: {payload[field]!r} not in {enum}")
    return errors
