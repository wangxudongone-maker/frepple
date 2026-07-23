#!/usr/bin/env python3
"""Merge completed translations from a newer PO catalog into an older catalog."""

import argparse
import ast
import re
from pathlib import Path


def field_value(lines, field):
    prefix = f"{field} "
    for index, line in enumerate(lines):
        if line.startswith(prefix):
            value = ast.literal_eval(line[len(prefix) :].strip())
            for continuation in lines[index + 1 :]:
                if not continuation.startswith('"'):
                    break
                value += ast.literal_eval(continuation)
            return value
    return None


def plural_values(lines):
    values = []
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


def key_for(lines):
    return (
        field_value(lines, "msgctxt"),
        field_value(lines, "msgid"),
        field_value(lines, "msgid_plural"),
    )


def translated(lines):
    if any("fuzzy" in line for line in lines if line.startswith("#,")):
        return False
    singular = field_value(lines, "msgstr")
    plurals = plural_values(lines)
    return bool(singular or any(plurals))


def translation_suffix(lines):
    for index, line in enumerate(lines):
        if line.startswith("msgstr"):
            return lines[index:]
    return []


def remove_fuzzy(lines):
    result = []
    for line in lines:
        if not line.startswith("#,") or "fuzzy" not in line:
            result.append(line)
            continue
        flags = [
            flag.strip() for flag in line[2:].split(",") if flag.strip() != "fuzzy"
        ]
        if flags:
            result.append("#, " + ", ".join(flags))
    return result


def split_blocks(text):
    return re.split(r"\n{2,}", text.replace("\r\n", "\n").strip())


def merge(source, target):
    source_blocks = [
        block.splitlines() for block in split_blocks(source.read_text(encoding="utf-8"))
    ]
    translations = {
        key_for(lines): translation_suffix(lines)
        for lines in source_blocks
        if key_for(lines)[1] and translated(lines)
    }
    target_blocks = split_blocks(target.read_text(encoding="utf-8"))
    merged = []
    count = 0
    for block in target_blocks:
        lines = block.splitlines()
        suffix = translations.get(key_for(lines))
        if not suffix:
            merged.append(block)
            continue
        first_msgstr = next(
            (index for index, line in enumerate(lines) if line.startswith("msgstr")),
            None,
        )
        if first_msgstr is None:
            merged.append(block)
            continue
        merged.append("\n".join(remove_fuzzy(lines[:first_msgstr]) + suffix))
        count += 1
    target.write_text("\n\n".join(merged) + "\n", encoding="utf-8", newline="\n")
    return count


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path, nargs="+")
    args = parser.parse_args()
    for target in args.target:
        print(f"{target}: merged {merge(args.source, target)} translations")


if __name__ == "__main__":
    main()
