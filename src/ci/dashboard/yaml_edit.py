"""Change one value in a YAML file without touching anything else.

The config files carry the reasoning behind every threshold, and that reasoning
is worth more than the numbers: it is the record of which choices were tested
against real data and why. `yaml.safe_load` then `yaml.dump` would silently
delete every comment, reorder keys and reformat lists. One round trip through a
dashboard would erase months of decisions.

So this does a surgical text replacement on the one line that holds the value.
Everything else in the file, byte for byte, survives.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml


class YamlEditError(RuntimeError):
    pass


def _fmt(value: Any) -> str:
    """Render a scalar the way YAML wants it, so a rewritten line re-parses."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value) if isinstance(value, float) else str(value)
    if value is None:
        return "null"
    if isinstance(value, list):
        return "[" + ", ".join(_fmt(v) for v in value) + "]"
    text = str(value)
    # Quote anything that YAML would otherwise read as a number, bool or null.
    if text == "" or re.fullmatch(r"[-+]?[\d.]+|true|false|null|yes|no|on|off",
                                  text, re.I):
        return f'"{text}"'
    if any(c in text for c in ":#{}[],&*!|>'\"%@`") or text != text.strip():
        return '"' + text.replace('"', '\\"') + '"'
    return text


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def find_line(lines: list[str], path: list[str]) -> int:
    """Index of the line holding the last key in `path`, following indentation.

    Plain text search for the final key would match the wrong one: `max_rows`
    and `weights` appear under several different parents in scoring.yaml.
    """
    depth = 0
    start = 0
    for i, key in enumerate(path):
        want = re.compile(rf"^(\s*)(?:- )?{re.escape(key)}\s*:")
        found = -1
        for n in range(start, len(lines)):
            line = lines[n]
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            here = _indent_of(line)
            if i and here <= depth and n > start:
                # Walked out of the parent block without finding it.
                break
            m = want.match(line)
            if m and (not i or here > depth):
                found = n
                break
        if found < 0:
            raise YamlEditError(f"could not find {'.'.join(path[:i + 1])}")
        depth = _indent_of(lines[found])
        start = found + 1
    return found


def set_in_text(original: str, path: list[str], value: Any) -> str:
    """Set one key in YAML text and return the new text. Nothing touches disk."""
    lines = original.splitlines()

    # A numeric segment means "the Nth item of this list". The tier table is a
    # list of inline flow maps, so the key being edited lives inside one line:
    #   - {name: "BREAKING OUT", min_views: 50000, max_age_hours: 24}
    if any(seg.isdigit() for seg in path):
        return _set_in_list(original, lines, path, value)

    n = find_line(lines, path)
    line = lines[n]

    head, _, tail = line.partition(":")
    comment = ""
    # Keep any trailing comment on the same line, it usually explains the value.
    stripped = tail.strip()
    if stripped and not stripped.startswith(("#", "{", "[")):
        m = re.search(r"\s+#", tail)
        if m:
            comment = tail[m.start():]
    elif stripped.startswith(("[", "{")):
        m = re.search(r"(?<=[\]}])\s+#", tail)
        if m:
            comment = tail[m.start():]
    elif stripped.startswith("#"):
        comment = "  " + stripped

    lines[n] = f"{head}: {_fmt(value)}{comment}"
    return _verified(original, lines)


def _verified(original: str, lines: list[str]) -> str:
    updated = "\n".join(lines) + ("\n" if original.endswith("\n") else "")
    try:
        yaml.safe_load(updated)
    except yaml.YAMLError as exc:
        raise YamlEditError(f"edit produced invalid YAML: {exc}") from exc
    return updated


def _set_in_list(original: str, lines: list[str], path: list[str], value: Any) -> str:
    """Edit a key inside the Nth item of a list, including inline flow maps."""
    idx_at = next(i for i, seg in enumerate(path) if seg.isdigit())
    parent, index, rest = path[:idx_at], int(path[idx_at]), path[idx_at + 1:]

    start = find_line(lines, parent) if parent else -1
    depth = _indent_of(lines[start]) if start >= 0 else -1

    seen, target = -1, -1
    for n in range(start + 1, len(lines)):
        line = lines[n]
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if _indent_of(line) <= depth and not line.lstrip().startswith("- "):
            break
        if line.lstrip().startswith("- "):
            seen += 1
            if seen == index:
                target = n
                break
    if target < 0:
        raise YamlEditError(f"could not find {'.'.join(path[:idx_at + 1])}")

    if not rest:
        raise YamlEditError("cannot replace a whole list item, edit one of its keys")

    key = rest[-1]

    # Two ways a list item can be written, and both appear in these configs.
    #
    #   flow:   - {name: "BREAKING OUT", min_views: 50000, max_age_hours: 24}
    #   block:  - name: today
    #             max_items_per_keyword: 20
    #
    # Flow keeps every key on the item's own line. Block spreads them over the
    # following lines until the next "- " or a dedent.
    line = lines[target]
    m = re.search(rf"(\b{re.escape(key)}\s*:\s*)([^,}}]+)", line)
    if m:
        # Preserve the column alignment the tier table is written with, so the
        # file still reads as a table afterwards.
        old = m.group(2)
        new = _fmt(value)
        pad = " " * max(0, len(old.rstrip()) - len(new)) if old != old.rstrip() else ""
        lines[target] = line[:m.start(2)] + new + pad + line[m.end(2):]
        return _verified(original, lines)

    item_indent = _indent_of(line)
    want = re.compile(rf"^\s*{re.escape(key)}\s*:")
    for n in range(target + 1, len(lines)):
        nxt = lines[n]
        if not nxt.strip() or nxt.lstrip().startswith("#"):
            continue
        if nxt.lstrip().startswith("- ") or _indent_of(nxt) <= item_indent:
            break          # next item, or out of the list entirely
        if want.match(nxt):
            head, _, tail = nxt.partition(":")
            keep = ""
            mm = re.search(r"\s+#", tail)
            if mm:
                keep = tail[mm.start():]
            lines[n] = f"{head}: {_fmt(value)}{keep}"
            return _verified(original, lines)

    raise YamlEditError(f"could not find {key} in list item {index}")


def apply(file: Path, changes: dict[str, Any]) -> dict[str, Any]:
    """Apply several dotted-path changes atomically.

    Everything is written to a temporary file and moved into place, so a failure
    half way through cannot leave a config the collector will refuse to load at
    6am tomorrow.
    """
    text = file.read_text()
    before = yaml.safe_load(text) or {}
    applied: list[str] = []

    # Every edit is made in memory first. If any one of them fails, nothing has
    # touched disk, so a rejected change can never leave a half-edited config
    # for the 6am run to choke on.
    for dotted, value in changes.items():
        path = [p for p in dotted.split(".") if p]
        if not path:
            raise YamlEditError("empty key path")
        text = set_in_text(text, path, value)
        applied.append(dotted)

    tmp = file.with_suffix(file.suffix + ".tmp")
    tmp.write_text(text)
    after = yaml.safe_load(text) or {}
    tmp.replace(file)
    return {"applied": applied, "keys": len(applied),
            "changed": sum(1 for k in changes
                           if _dig(before, k) != _dig(after, k))}


def _dig(data: Any, dotted: str) -> Any:
    for part in dotted.split("."):
        if not isinstance(data, dict):
            return None
        data = data.get(part)
    return data


def set_value(file: Path, path: list[str], value: Any) -> str:
    """Convenience wrapper: read a file and return its edited text."""
    return set_in_text(file.read_text(), path, value)
