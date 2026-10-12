"""Canonical member references for model prose, quoted messages and reports."""
from __future__ import annotations

import re

REFERENCE = re.compile(r"\[([^\]\n]{1,128})\]")
ALIAS = re.compile(r"(?<![A-Za-z0-9_])U\d+(?![A-Za-z0-9_])")
STRUCTURED_AT = re.compile(r"\[\s*@?id\s*:\s*([^;\]\s]+)\s*;\s*nickname\s*:[^\]]*\]", re.I)


def canonical_text(text: str, aliases: dict[str, str], known: set[str]) -> str:
    """Turn internal U IDs and transport mentions into [member ID] references."""
    def reference(value):
        uid = aliases.get(value, value)
        return f"[{uid}]" if uid in known else "某位成员"
    text = STRUCTURED_AT.sub(lambda m: reference(m.group(1)), str(text))
    return ALIAS.sub(lambda m: reference(m.group(0)), text)


def plain_text(text: str, names: dict[str, str]) -> str:
    return REFERENCE.sub(lambda m: names.get(m.group(1), m.group(0)), str(text))


def model_prose(text: str, aliases: dict[str, str], known: set[str]) -> str:
    # Evidence IDs help validation, but are meaningless to the report reader.
    text = re.sub(r"(?<![A-Za-z0-9_])M\d+(?![A-Za-z0-9_])", "原话", str(text))
    return canonical_text(text, aliases, known)


def member_names(members: list[dict]) -> dict[str, str]:
    names = {m["id"]: ("（机器人）" if m.get("is_bot") else "")
             + (re.sub(r"\s+", " ", str(m["name"])).strip() or m["id"]) for m in members}
    counts = {}
    for name in names.values():
        counts[name] = counts.get(name, 0) + 1
    return {uid: name + (f"（{uid[-4:]}）" if counts[name] > 1 else "") for uid, name in names.items()}
