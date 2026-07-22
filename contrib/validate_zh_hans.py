#!/usr/bin/env python3
"""Validate the Simplified Chinese translation catalogs without dependencies."""

from __future__ import annotations

import ast
import json
import re
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PO_FILES = (
    ROOT / "freppledb/locale/zh_Hans/zh_Hans.po",
    ROOT / "freppledb/locale/zh_Hans/LC_MESSAGES/django.po",
    ROOT / "freppledb/locale/zh_Hans/LC_MESSAGES/djangojs.po",
    ROOT / "freppledb/common/static/common/po/zh-hans.po",
)
VUE_JSON = ROOT / "freppledb/input/frontend/src/i18n/translations/zh-hans.json"
PLACEHOLDER_RE = re.compile(
    r"%\([^)]+\)[#0 +\-]?\d*(?:\.\d+)?[a-zA-Z]"
    r"|{{[^}]+}}|(?<!%)%(?:\d+\$)?[sdif]"
)
TAG_RE = re.compile(r"</?([a-zA-Z][\w-]*)\b")


def po_value(lines: list[str], field: str) -> str | None:
    prefix = f"{field} "
    for index, line in enumerate(lines):
        if not line.startswith(prefix):
            continue
        value = ast.literal_eval(line[len(prefix) :].strip())
        for continuation in lines[index + 1 :]:
            if not continuation.startswith('"'):
                break
            value += ast.literal_eval(continuation)
        return value
    return None


def plural_values(lines: list[str]) -> list[str]:
    values: list[str] = []
    for index, line in enumerate(lines):
        match = re.match(r"msgstr\[(\d+)]\s+(.*)", line)
        if not match:
            continue
        value = ast.literal_eval(match.group(2))
        for continuation in lines[index + 1 :]:
            if not continuation.startswith('"'):
                break
            value += ast.literal_eval(continuation)
        slot = int(match.group(1))
        while len(values) <= slot:
            values.append("")
        values[slot] = value
    return values


def normalized_placeholders(value: str) -> Counter[str]:
    return Counter(re.sub(r"\s+", "", item) for item in PLACEHOLDER_RE.findall(value))


def html_tags(value: str) -> Counter[str]:
    return Counter(tag.lower() for tag in TAG_RE.findall(value))


def validate_po(path: Path) -> tuple[int, list[str]]:
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    errors: list[str] = []
    entries = 0
    for block in re.split(r"\n{2,}", text):
        lines = block.splitlines()
        msgid = po_value(lines, "msgid")
        if not msgid:
            continue
        entries += 1
        msgstr = po_value(lines, "msgstr")
        plurals = plural_values(lines)
        if not msgstr and not any(plurals):
            errors.append(f"empty translation: {msgid!r}")
            continue
        if any("fuzzy" in line for line in lines if line.startswith("#,")):
            errors.append(f"fuzzy translation: {msgid!r}")
        translated = msgstr if msgstr is not None else plurals[0]
        if normalized_placeholders(msgid) != normalized_placeholders(translated):
            errors.append(f"placeholder mismatch: {msgid!r}")
        if html_tags(msgid) != html_tags(translated):
            errors.append(f"HTML tag mismatch: {msgid!r}")
    return entries, errors


def main() -> None:
    total = 0
    failures: list[str] = []
    for path in PO_FILES:
        entries, errors = validate_po(path)
        total += entries
        failures.extend(f"{path.relative_to(ROOT)}: {error}" for error in errors)

    vue = json.loads(VUE_JSON.read_text(encoding="utf-8"))
    for key, value in vue.items():
        if not value:
            failures.append(f"{VUE_JSON.relative_to(ROOT)}: empty translation: {key!r}")
        if key == value and key != "ID":
            failures.append(f"{VUE_JSON.relative_to(ROOT)}: untranslated value: {key!r}")

    settings = (ROOT / "djangosettings.py").read_text(encoding="utf-8")
    expected = 'LANGUAGE_CODE = os.environ.get("FREPPLE_LANGUAGE_CODE", "zh-hans")'
    if expected not in settings:
        failures.append("djangosettings.py: Simplified Chinese is not the default language")

    if failures:
        raise SystemExit("\n".join(failures))
    print(f"Simplified Chinese validation passed: {total} PO entries, {len(vue)} Vue entries")


if __name__ == "__main__":
    main()

