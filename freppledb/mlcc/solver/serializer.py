"""Deterministic JSON serialization for solver-neutral planning instances."""

import hashlib
import json
from dataclasses import fields, is_dataclass
from decimal import Decimal


def decimal_string(value):
    if value == 0:
        return "0"
    normalized = value.normalize()
    return format(normalized, "f")


def to_primitive(value):
    if isinstance(value, Decimal):
        return decimal_string(value)
    if is_dataclass(value):
        return {
            field.name: to_primitive(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, dict):
        return {str(key): to_primitive(value[key]) for key in sorted(value)}
    if isinstance(value, (tuple, list)):
        return [to_primitive(item) for item in value]
    return value


def planning_instance_json(instance, pretty=False):
    options = {
        "ensure_ascii": False,
        "sort_keys": True,
    }
    if pretty:
        options["indent"] = 2
    else:
        options["separators"] = (",", ":")
    return json.dumps(to_primitive(instance), **options) + "\n"


def planning_instance_fingerprint(instance):
    payload = planning_instance_json(instance, pretty=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
