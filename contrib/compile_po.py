#!/usr/bin/env python3
"""Compile a UTF-8 gettext PO file to GNU MO without external dependencies."""

import argparse
import ast
import re
import struct
from pathlib import Path


def field_value(lines, field):
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


def plural_values(lines):
    result = {}
    for index, line in enumerate(lines):
        match = re.match(r"msgstr\[(\d+)]\s+(.*)", line)
        if not match:
            continue
        value = ast.literal_eval(match.group(2))
        for continuation in lines[index + 1 :]:
            if not continuation.startswith('"'):
                break
            value += ast.literal_eval(continuation)
        result[int(match.group(1))] = value
    return [result[index] for index in sorted(result)]


def messages(path):
    catalog = {}
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    for block in re.split(r"\n{2,}", text):
        lines = block.splitlines()
        if any("fuzzy" in line for line in lines if line.startswith("#,")):
            continue
        msgid = field_value(lines, "msgid")
        if msgid is None:
            continue
        context = field_value(lines, "msgctxt")
        plural = field_value(lines, "msgid_plural")
        translations = plural_values(lines)
        msgstr = field_value(lines, "msgstr")
        if plural is not None:
            if not translations or not any(translations):
                continue
            key = msgid + "\0" + plural
            value = "\0".join(translations)
        else:
            if msgid and not msgstr:
                continue
            key = msgid
            value = msgstr or ""
        if context:
            key = context + "\x04" + key
        catalog[key] = value
    return catalog


def compile_catalog(source, target):
    catalog = messages(source)
    keys = sorted(catalog)
    ids = [key.encode("utf-8") for key in keys]
    values = [catalog[key].encode("utf-8") for key in keys]
    count = len(keys)
    original_table_offset = 28
    translation_table_offset = original_table_offset + count * 8
    original_data_offset = translation_table_offset + count * 8
    ids_blob = b"\0".join(ids) + b"\0"
    translation_data_offset = original_data_offset + len(ids_blob)
    values_blob = b"\0".join(values) + b"\0"

    original_table = []
    offset = original_data_offset
    for value in ids:
        original_table.append((len(value), offset))
        offset += len(value) + 1
    translation_table = []
    offset = translation_data_offset
    for value in values:
        translation_table.append((len(value), offset))
        offset += len(value) + 1

    output = [
        struct.pack(
            "<7I",
            0x950412DE,
            0,
            count,
            original_table_offset,
            translation_table_offset,
            0,
            0,
        )
    ]
    output.extend(struct.pack("<2I", *entry) for entry in original_table)
    output.extend(struct.pack("<2I", *entry) for entry in translation_table)
    output.extend((ids_blob, values_blob))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"".join(output))
    return count


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    args = parser.parse_args()
    print(
        f"{args.target}: compiled {compile_catalog(args.source, args.target)} messages"
    )


if __name__ == "__main__":
    main()
