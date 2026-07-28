"""Pure Python data contract consumed by a future MLCC scheduling solver."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

SCHEMA_VERSION = "mlcc-planning-instance/v1"
PROCESS_STAGE_ORDER = (
    "stacking",
    "lamination",
    "cutting",
    "debinding",
    "sintering",
)


@dataclass(frozen=True)
class PlanningWindow:
    origin: str
    horizon_minutes: int
    freeze_minutes: int
    timezone: str


@dataclass(frozen=True)
class CustomerOrder:
    id: str
    item_id: str
    batch_id: str
    quantity: Decimal
    due_minute: int | None
    priority: int


@dataclass(frozen=True)
class ProductionBatch:
    id: str
    order_id: str
    item_id: str
    product_family: str
    quantity: Decimal
    due_minute: int | None
    priority: int
    quality_hold: bool
    schedulable: bool


@dataclass(frozen=True)
class ProcessStep:
    id: str
    batch_id: str
    sequence: int
    stage: str
    operation_id: str
    quantity: Decimal
    duration_minutes: int
    minimum_batch: Decimal | None
    maximum_batch: Decimal | None
    candidate_resource_ids: tuple[str, ...] = ()
    certified_resource_ids: tuple[str, ...] = ()
    assigned_resource_id: str | None = None
    recipe_id: str | None = None
    predecessor_ids: tuple[str, ...] = ()
    minimum_wait_minutes: int = 0
    maximum_wait_minutes: int | None = None
    required_material_ids: tuple[str, ...] = ()
    started: bool = False
    frozen: bool = False
    original_start_minute: int | None = None
    original_end_minute: int | None = None
    recipe_resolution: str = "resolved"
    load_requirements: tuple["FurnaceLoadRequirement", ...] = ()


@dataclass(frozen=True)
class CalendarInterval:
    start_minute: int
    end_minute: int
    kind: str


@dataclass(frozen=True)
class Equipment:
    id: str
    resource_id: str
    capacity: Decimal | None
    load_unit: str | None
    shifts: tuple[CalendarInterval, ...] = ()
    downtimes: tuple[CalendarInterval, ...] = ()
    maintenance: tuple[CalendarInterval, ...] = ()


@dataclass(frozen=True)
class EquipmentCapability:
    id: str
    resource_id: str
    stage: str
    recipe_id: str | None
    item_id: str | None
    minimum_quantity: Decimal | None
    maximum_quantity: Decimal | None
    enabled: bool


@dataclass(frozen=True)
class Recipe:
    id: str
    name: str
    version: str
    stage: str
    effective_date: str
    expiry_date: str | None
    active: bool
    setup_family: str | None
    parameters: dict[str, Any] = field(default_factory=dict)
    furnace_program_key: str | None = None
    compatibility_group: str | None = None


@dataclass(frozen=True)
class FurnaceLoadRequirement:
    resource_id: str
    quantity: int | None
    load_unit: str | None
    source_quantity: Decimal
    source_unit: str | None
    conversion_id: str | None = None
    conversion_numerator: int | None = None
    conversion_denominator: int | None = None


@dataclass(frozen=True)
class FrozenFurnaceLoad:
    id: str
    stage: str
    resource_id: str
    recipe_id: str
    furnace_program_key: str
    start_minute: int
    end_minute: int
    capacity: int
    loaded_quantity: int
    load_unit: str
    member_task_ids: tuple[str, ...]
    status: str


@dataclass(frozen=True)
class CompatibilityRule:
    id: str
    stage: str
    family_a: str
    family_b: str
    rule_type: str
    enabled: bool


@dataclass(frozen=True)
class SetupRule:
    id: str
    resource_id: str | None
    stage: str
    from_recipe_id: str
    to_recipe_id: str
    duration_minutes: int


@dataclass(frozen=True)
class MaterialAvailability:
    id: str
    item_id: str
    batch_id: str | None
    quantity: Decimal
    available_minute: int | None
    kind: str


@dataclass(frozen=True)
class PlanningInstance:
    window: PlanningWindow
    customer_orders: tuple[CustomerOrder, ...] = ()
    batches: tuple[ProductionBatch, ...] = ()
    steps: tuple[ProcessStep, ...] = ()
    equipment: tuple[Equipment, ...] = ()
    capabilities: tuple[EquipmentCapability, ...] = ()
    recipes: tuple[Recipe, ...] = ()
    compatibility_rules: tuple[CompatibilityRule, ...] = ()
    setup_rules: tuple[SetupRule, ...] = ()
    materials: tuple[MaterialAvailability, ...] = ()
    frozen_furnace_loads: tuple[FrozenFurnaceLoad, ...] = ()
    schema_version: str = SCHEMA_VERSION

    @property
    def counts(self):
        return {
            "orders": len(self.customer_orders),
            "batches": len(self.batches),
            "tasks": len(self.steps),
            "equipment": len(self.equipment),
        }
