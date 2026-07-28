"""Deterministic JSON serialization for solver-neutral planning instances."""

import hashlib
import json
from dataclasses import fields, is_dataclass
from decimal import Decimal

from .schema import (
    SCHEMA_VERSION,
    CalendarInterval,
    CompatibilityRule,
    CustomerOrder,
    Equipment,
    EquipmentCapability,
    FrozenFurnaceLoad,
    FurnaceLoadRequirement,
    MaterialAvailability,
    PlanningInstance,
    PlanningWindow,
    ProcessStep,
    ProductionBatch,
    Recipe,
    SetupRule,
)


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


def _decimal(value):
    return None if value is None else Decimal(str(value))


def planning_instance_from_dict(payload):
    """Build the pure data contract without importing or returning ORM objects."""

    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            "Unsupported planning instance schema version: "
            f"{payload.get('schema_version')!r}"
        )
    window = payload["window"]
    return PlanningInstance(
        window=PlanningWindow(
            origin=str(window["origin"]),
            horizon_minutes=int(window["horizon_minutes"]),
            freeze_minutes=int(window["freeze_minutes"]),
            timezone=str(window["timezone"]),
        ),
        customer_orders=tuple(
            CustomerOrder(
                id=str(item["id"]),
                item_id=str(item["item_id"]),
                batch_id=str(item["batch_id"]),
                quantity=_decimal(item["quantity"]),
                due_minute=(
                    None if item.get("due_minute") is None else int(item["due_minute"])
                ),
                priority=int(item["priority"]),
            )
            for item in payload.get("customer_orders", ())
        ),
        batches=tuple(
            ProductionBatch(
                id=str(item["id"]),
                order_id=str(item["order_id"]),
                item_id=str(item["item_id"]),
                product_family=str(item["product_family"]),
                quantity=_decimal(item["quantity"]),
                due_minute=(
                    None if item.get("due_minute") is None else int(item["due_minute"])
                ),
                priority=int(item["priority"]),
                quality_hold=bool(item["quality_hold"]),
                schedulable=bool(item["schedulable"]),
            )
            for item in payload.get("batches", ())
        ),
        steps=tuple(
            ProcessStep(
                id=str(item["id"]),
                batch_id=str(item["batch_id"]),
                sequence=int(item["sequence"]),
                stage=str(item["stage"]),
                operation_id=str(item["operation_id"]),
                quantity=_decimal(item["quantity"]),
                duration_minutes=int(item["duration_minutes"]),
                minimum_batch=_decimal(item.get("minimum_batch")),
                maximum_batch=_decimal(item.get("maximum_batch")),
                candidate_resource_ids=tuple(item.get("candidate_resource_ids", ())),
                certified_resource_ids=tuple(item.get("certified_resource_ids", ())),
                assigned_resource_id=item.get("assigned_resource_id"),
                recipe_id=item.get("recipe_id"),
                predecessor_ids=tuple(item.get("predecessor_ids", ())),
                minimum_wait_minutes=int(item.get("minimum_wait_minutes", 0)),
                maximum_wait_minutes=(
                    None
                    if item.get("maximum_wait_minutes") is None
                    else int(item["maximum_wait_minutes"])
                ),
                required_material_ids=tuple(item.get("required_material_ids", ())),
                started=bool(item.get("started", False)),
                frozen=bool(item.get("frozen", False)),
                original_start_minute=(
                    None
                    if item.get("original_start_minute") is None
                    else int(item["original_start_minute"])
                ),
                original_end_minute=(
                    None
                    if item.get("original_end_minute") is None
                    else int(item["original_end_minute"])
                ),
                recipe_resolution=str(item.get("recipe_resolution", "resolved")),
                load_requirements=tuple(
                    FurnaceLoadRequirement(
                        resource_id=str(requirement["resource_id"]),
                        quantity=(
                            None
                            if requirement.get("quantity") is None
                            else int(requirement["quantity"])
                        ),
                        load_unit=requirement.get("load_unit"),
                        source_quantity=_decimal(requirement["source_quantity"]),
                        source_unit=requirement.get("source_unit"),
                        conversion_id=requirement.get("conversion_id"),
                        conversion_numerator=(
                            None
                            if requirement.get("conversion_numerator") is None
                            else int(requirement["conversion_numerator"])
                        ),
                        conversion_denominator=(
                            None
                            if requirement.get("conversion_denominator") is None
                            else int(requirement["conversion_denominator"])
                        ),
                    )
                    for requirement in item.get("load_requirements", ())
                ),
            )
            for item in payload.get("steps", ())
        ),
        equipment=tuple(
            Equipment(
                id=str(item["id"]),
                resource_id=str(item["resource_id"]),
                capacity=_decimal(item.get("capacity")),
                load_unit=item.get("load_unit"),
                shifts=tuple(
                    CalendarInterval(
                        start_minute=int(interval["start_minute"]),
                        end_minute=int(interval["end_minute"]),
                        kind=str(interval["kind"]),
                    )
                    for interval in item.get("shifts", ())
                ),
                downtimes=tuple(
                    CalendarInterval(
                        start_minute=int(interval["start_minute"]),
                        end_minute=int(interval["end_minute"]),
                        kind=str(interval["kind"]),
                    )
                    for interval in item.get("downtimes", ())
                ),
                maintenance=tuple(
                    CalendarInterval(
                        start_minute=int(interval["start_minute"]),
                        end_minute=int(interval["end_minute"]),
                        kind=str(interval["kind"]),
                    )
                    for interval in item.get("maintenance", ())
                ),
            )
            for item in payload.get("equipment", ())
        ),
        capabilities=tuple(
            EquipmentCapability(
                id=str(item["id"]),
                resource_id=str(item["resource_id"]),
                stage=str(item["stage"]),
                recipe_id=item.get("recipe_id"),
                item_id=item.get("item_id"),
                minimum_quantity=_decimal(item.get("minimum_quantity")),
                maximum_quantity=_decimal(item.get("maximum_quantity")),
                enabled=bool(item["enabled"]),
            )
            for item in payload.get("capabilities", ())
        ),
        recipes=tuple(
            Recipe(
                id=str(item["id"]),
                name=str(item["name"]),
                version=str(item["version"]),
                stage=str(item["stage"]),
                effective_date=str(item["effective_date"]),
                expiry_date=item.get("expiry_date"),
                active=bool(item["active"]),
                setup_family=item.get("setup_family"),
                parameters=dict(item.get("parameters", {})),
                furnace_program_key=item.get("furnace_program_key"),
                compatibility_group=item.get("compatibility_group"),
            )
            for item in payload.get("recipes", ())
        ),
        compatibility_rules=tuple(
            CompatibilityRule(
                id=str(item["id"]),
                stage=str(item["stage"]),
                family_a=str(item["family_a"]),
                family_b=str(item["family_b"]),
                rule_type=str(item["rule_type"]),
                enabled=bool(item["enabled"]),
            )
            for item in payload.get("compatibility_rules", ())
        ),
        setup_rules=tuple(
            SetupRule(
                id=str(item["id"]),
                resource_id=item.get("resource_id"),
                stage=str(item["stage"]),
                from_recipe_id=str(item["from_recipe_id"]),
                to_recipe_id=str(item["to_recipe_id"]),
                duration_minutes=int(item["duration_minutes"]),
            )
            for item in payload.get("setup_rules", ())
        ),
        materials=tuple(
            MaterialAvailability(
                id=str(item["id"]),
                item_id=str(item["item_id"]),
                batch_id=item.get("batch_id"),
                quantity=_decimal(item["quantity"]),
                available_minute=(
                    None
                    if item.get("available_minute") is None
                    else int(item["available_minute"])
                ),
                kind=str(item["kind"]),
            )
            for item in payload.get("materials", ())
        ),
        frozen_furnace_loads=tuple(
            FrozenFurnaceLoad(
                id=str(item["id"]),
                stage=str(item["stage"]),
                resource_id=str(item["resource_id"]),
                recipe_id=str(item["recipe_id"]),
                furnace_program_key=str(item["furnace_program_key"]),
                start_minute=int(item["start_minute"]),
                end_minute=int(item["end_minute"]),
                capacity=int(item["capacity"]),
                loaded_quantity=int(item["loaded_quantity"]),
                load_unit=str(item["load_unit"]),
                member_task_ids=tuple(item.get("member_task_ids", ())),
                status=str(item["status"]),
            )
            for item in payload.get("frozen_furnace_loads", ())
        ),
    )


def planning_instance_from_json(payload):
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")
    return planning_instance_from_dict(json.loads(payload))


def load_planning_instance(path):
    with open(path, "r", encoding="utf-8") as stream:
        return planning_instance_from_dict(json.load(stream))
