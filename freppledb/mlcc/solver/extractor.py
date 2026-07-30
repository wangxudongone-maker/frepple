"""Extract frePPLe and MLCC ORM data into the pure planning schema."""

from collections import defaultdict
from dataclasses import replace
from datetime import datetime, time, timedelta
from decimal import Decimal, ROUND_CEILING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.db import DEFAULT_DB_ALIAS
from django.db.models import F, Q
from django.utils import timezone

from freppledb.input.models import (
    Buffer,
    CalendarBucket,
    Demand,
    ManufacturingOrder,
    OperationDependency,
    OperationMaterial,
    OperationPlanResource,
    OperationResource,
    Resource,
)
from freppledb.mlcc.models import (
    MlccCompatibilityRule,
    MlccEquipmentCapability,
    MlccFurnaceLoad,
    MlccFurnaceProgram,
    MlccFurnaceStateSnapshot,
    MlccFurnaceTransition,
    MlccFurnaceTransitionRule,
    MlccLoadUnitConversion,
    MlccQualityHold,
    MlccRecipe,
    MlccSetupMatrix,
)

from .schema import (
    PROCESS_STAGE_ORDER,
    CalendarInterval,
    CompatibilityRule,
    CustomerOrder,
    Equipment,
    EquipmentCapability,
    FrozenFurnaceLoad,
    FrozenFurnaceTransition,
    FurnaceProgram,
    FurnaceLoadRequirement,
    FurnaceStateSnapshot,
    FurnaceTransitionRule,
    MaterialAvailability,
    PlanningInstance,
    PlanningWindow,
    ProcessStep,
    ProductionBatch,
    Recipe,
    SetupRule,
)
from .transition_rules import (
    stable_furnace_state_id,
    stable_furnace_transition_id,
    stable_transition_rule_id,
)


def stable_id(kind, value):
    return f"{kind}:{value}"


def timedelta_minutes(value):
    if value is None:
        return None
    microseconds = (
        value.days * 86400 * 1_000_000 + value.seconds * 1_000_000 + value.microseconds
    )
    minutes = Decimal(microseconds) / Decimal(60_000_000)
    return int(minutes.to_integral_value(rounding=ROUND_CEILING))


def operation_duration_minutes(fixed, per_unit, quantity):
    def microseconds(value):
        if value is None:
            return Decimal("0")
        return Decimal(
            value.days * 86400 * 1_000_000
            + value.seconds * 1_000_000
            + value.microseconds
        )

    total = microseconds(fixed) + microseconds(per_unit) * Decimal(quantity)
    minutes = total / Decimal(60_000_000)
    return int(minutes.to_integral_value(rounding=ROUND_CEILING))


class PlanningInstanceExtractor:
    """Database adapter. Returned objects contain no Django model instances."""

    def __init__(
        self,
        database=DEFAULT_DB_ALIAS,
        horizon_start=None,
        horizon_days=14,
        freeze_hours=48,
        factory_timezone=None,
        source=None,
    ):
        self.database = database
        self.horizon_days = int(horizon_days)
        self.freeze_hours = int(freeze_hours)
        self.timezone_name = factory_timezone or settings.TIME_ZONE
        try:
            self.zone = ZoneInfo(self.timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"Unknown factory timezone: {self.timezone_name}") from exc
        self.source = source
        self.origin = self._normalize_datetime(horizon_start) if horizon_start else None

    def _normalize_datetime(self, value):
        if isinstance(value, str):
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if timezone.is_naive(value):
            value = value.replace(tzinfo=self.zone)
        return value.astimezone(self.zone).replace(second=0, microsecond=0)

    def _minute(self, value):
        if value is None:
            return None
        value = self._normalize_datetime(value)
        return int((value - self.origin).total_seconds() // 60)

    def _database_datetime(self, value):
        """Return a datetime in the form accepted by the configured ORM."""

        if value is None or settings.USE_TZ:
            return value
        return value.astimezone(self.zone).replace(tzinfo=None)

    def _source_filter(self, queryset):
        return queryset.filter(source=self.source) if self.source else queryset

    def _orders(self):
        orders = (
            ManufacturingOrder.objects.using(self.database)
            .filter(
                type__in=("MO", "WO"),
                operation__mlcc_process_stage__in=PROCESS_STAGE_ORDER,
            )
            .select_related("operation", "operation__item", "demand", "demand__item")
            .order_by("reference")
        )
        return list(self._source_filter(orders))

    def _determine_origin(self, orders):
        if self.origin:
            return
        candidates = [
            value
            for order in orders
            for value in (order.startdate, order.enddate, order.due)
            if value is not None
        ]
        if candidates:
            self.origin = self._normalize_datetime(min(candidates))
        else:
            # An empty database still has to produce byte-identical business JSON.
            # Callers that need a different empty horizon can pass horizon_start.
            self.origin = datetime(1970, 1, 1, tzinfo=self.zone)

    def extract(self):
        orders = self._orders()
        self._determine_origin(orders)
        self.horizon_end = self.origin + timedelta(days=self.horizon_days)

        groups = self._group_orders(orders)
        recipes, recipe_objects = self._extract_recipes(orders)
        furnace_programs = self._extract_furnace_programs()
        task_recipes = self._select_task_recipes(orders, recipe_objects)
        resources_by_operation = self._resource_candidates(orders)
        assigned_resources = self._assigned_resources(orders)
        capabilities, capability_objects = self._extract_capabilities(
            resources_by_operation
        )
        steps = self._extract_steps(
            groups,
            task_recipes,
            resources_by_operation,
            assigned_resources,
            capability_objects,
        )
        customer_orders, batches = self._extract_orders_and_batches(groups)
        steps, materials = self._extract_materials(steps, orders)
        equipment = self._extract_equipment(
            steps, resources_by_operation, assigned_resources
        )
        frozen_furnace_loads = self._extract_frozen_furnace_loads(steps)
        frozen_furnace_transitions = self._extract_frozen_furnace_transitions(
            frozen_furnace_loads
        )
        predecessors = {
            item.successor_load_id: item.predecessor_load_id
            for item in frozen_furnace_transitions
        }
        successors = {
            item.predecessor_load_id: item.successor_load_id
            for item in frozen_furnace_transitions
            if item.predecessor_load_id
        }
        frozen_furnace_loads = tuple(
            replace(
                item,
                predecessor_load_id=predecessors.get(item.id),
                successor_load_id=successors.get(item.id),
            )
            for item in frozen_furnace_loads
        )

        window = PlanningWindow(
            origin=self.origin.isoformat(),
            horizon_minutes=self.horizon_days * 24 * 60,
            freeze_minutes=self.freeze_hours * 60,
            timezone=self.timezone_name,
        )
        return PlanningInstance(
            window=window,
            customer_orders=tuple(sorted(customer_orders, key=lambda item: item.id)),
            batches=tuple(sorted(batches, key=lambda item: item.id)),
            steps=tuple(sorted(steps, key=lambda item: item.id)),
            equipment=tuple(sorted(equipment, key=lambda item: item.id)),
            capabilities=tuple(sorted(capabilities, key=lambda item: item.id)),
            recipes=tuple(sorted(recipes, key=lambda item: item.id)),
            furnace_programs=furnace_programs,
            furnace_state_snapshots=self._extract_furnace_state_snapshots(equipment),
            furnace_transition_rules=self._extract_furnace_transition_rules(),
            compatibility_rules=self._extract_compatibility_rules(),
            setup_rules=self._extract_setup_rules(),
            materials=tuple(sorted(materials, key=lambda item: item.id)),
            frozen_furnace_loads=frozen_furnace_loads,
            frozen_furnace_transitions=frozen_furnace_transitions,
        )

    @staticmethod
    def _batch_key(order):
        return (
            (getattr(order, "mlcc_lot_number", None) or "").strip()
            or (order.batch or "").strip()
            or order.reference
        )

    def _group_orders(self, orders):
        groups = defaultdict(list)
        for order in orders:
            groups[self._batch_key(order)].append(order)
        return {
            key: sorted(
                value,
                key=lambda order: (
                    PROCESS_STAGE_ORDER.index(order.operation.mlcc_process_stage),
                    order.reference,
                ),
            )
            for key, value in sorted(groups.items())
        }

    def _extract_recipes(self, orders):
        queryset = MlccRecipe.objects.using(self.database).select_related(
            "item", "operation", "furnace_program"
        )
        queryset = self._source_filter(queryset).order_by(
            "name", "version", "effective_date", "id"
        )
        recipes = []
        objects = {}
        for recipe in queryset:
            identifier = stable_id("recipe", f"{recipe.name}:{recipe.version}")
            parameters = (
                recipe.parameters if isinstance(recipe.parameters, dict) else {}
            )
            recipes.append(
                Recipe(
                    id=identifier,
                    name=recipe.name,
                    version=recipe.version,
                    stage=recipe.process_stage,
                    effective_date=recipe.effective_date.isoformat(),
                    expiry_date=(
                        recipe.expiry_date.isoformat() if recipe.expiry_date else None
                    ),
                    active=recipe.active,
                    setup_family=parameters.get("setup_family"),
                    parameters=parameters,
                    furnace_program_key=recipe.furnace_program_key,
                    furnace_program_id=(
                        stable_id("furnace_program", recipe.furnace_program_id)
                        if recipe.furnace_program_id
                        else None
                    ),
                    compatibility_group=recipe.compatibility_group,
                )
            )
            objects[recipe.pk] = (recipe, identifier)
        return recipes, objects

    def _extract_furnace_programs(self):
        queryset = self._source_filter(
            MlccFurnaceProgram.objects.using(self.database).all()
        ).order_by("process_stage", "program_key", "version", "id")
        return tuple(
            FurnaceProgram(
                id=stable_id("furnace_program", row.id),
                program_key=row.program_key,
                version=row.version,
                stage=row.process_stage,
                atmosphere_key=row.atmosphere_key,
                required_pre_state_key=row.required_pre_state_key,
                resulting_post_state_key=row.resulting_post_state_key,
                effective_date=row.effective_date.isoformat(),
                expiry_date=row.expiry_date.isoformat() if row.expiry_date else None,
                active=row.active,
            )
            for row in queryset
        )

    def _select_task_recipes(self, orders, recipe_objects):
        result = {}
        for order in orders:
            stage = order.operation.mlcc_process_stage
            item_id = order.operation.item_id
            version = (getattr(order, "mlcc_recipe_version", None) or "").strip()
            candidates = [
                value
                for value in recipe_objects.values()
                if value[0].process_stage == stage
                and value[0].operation_id in (None, order.operation_id)
                and value[0].item_id in (None, item_id)
            ]
            candidates = [
                value
                for value in candidates
                if not version or value[0].version == version
            ]
            candidates.sort(
                key=lambda value: (
                    not value[0].active,
                    -value[0].effective_date.toordinal(),
                    value[1],
                )
            )
            active = [
                value
                for value in candidates
                if value[0].active
                and value[0].effective_date <= self.origin.date()
                and (
                    value[0].expiry_date is None
                    or value[0].expiry_date >= self.origin.date()
                )
            ]
            if len(active) == 1:
                result[order.reference] = (*active[0], "resolved")
            elif len(active) > 1:
                result[order.reference] = (None, None, "ambiguous")
            elif candidates:
                result[order.reference] = (*candidates[0], "resolved")
            else:
                result[order.reference] = (None, None, "missing")
        return result

    def _resource_candidates(self, orders):
        operation_ids = sorted({order.operation_id for order in orders})
        result = defaultdict(list)
        queryset = (
            OperationResource.objects.using(self.database)
            .filter(operation_id__in=operation_ids)
            .select_related("resource")
            .order_by("operation_id", "priority", "resource_id", "id")
        )
        for row in queryset:
            result[row.operation_id].append(row.resource_id)
        return {key: tuple(dict.fromkeys(value)) for key, value in result.items()}

    def _assigned_resources(self, orders):
        references = [order.reference for order in orders]
        queryset = (
            OperationPlanResource.objects.using(self.database)
            .filter(operationplan_id__in=references)
            .order_by("operationplan_id", "resource_id", "id")
        )
        result = {}
        for row in queryset:
            result.setdefault(row.operationplan_id, row.resource_id)
        return result

    def _extract_capabilities(self, resources_by_operation):
        resource_ids = sorted(
            {
                resource
                for values in resources_by_operation.values()
                for resource in values
            }
        )
        queryset = (
            MlccEquipmentCapability.objects.using(self.database)
            .filter(resource_id__in=resource_ids)
            .select_related("recipe", "item")
            .order_by("resource_id", "process_stage", "recipe_id", "item_id", "id")
        )
        queryset = self._source_filter(queryset)
        capabilities = []
        objects = []
        for row in queryset:
            recipe_id = (
                stable_id("recipe", f"{row.recipe.name}:{row.recipe.version}")
                if row.recipe_id
                else None
            )
            identifier = stable_id(
                "capability",
                ":".join(
                    (
                        row.resource_id,
                        row.process_stage,
                        recipe_id or "*",
                        row.item_id or "*",
                    )
                ),
            )
            capabilities.append(
                EquipmentCapability(
                    id=identifier,
                    resource_id=stable_id("resource", row.resource_id),
                    stage=row.process_stage,
                    recipe_id=recipe_id,
                    item_id=stable_id("item", row.item_id) if row.item_id else None,
                    minimum_quantity=row.minimum_quantity,
                    maximum_quantity=row.maximum_quantity,
                    enabled=row.enabled,
                )
            )
            objects.append((row, identifier))
        return capabilities, objects

    def _extract_steps(
        self,
        groups,
        task_recipes,
        resources_by_operation,
        assigned_resources,
        capabilities,
    ):
        candidate_resource_names = sorted(
            {name for values in resources_by_operation.values() for name in values}
        )
        resource_load_data = {
            row.name: ((getattr(row, "mlcc_load_unit", None) or "").strip() or None,)
            for row in Resource.objects.using(self.database)
            .filter(name__in=candidate_resource_names)
            .order_by("name")
        }
        conversions = list(
            self._source_filter(
                MlccLoadUnitConversion.objects.using(self.database).filter(enabled=True)
            ).order_by("item_id", "from_unit", "to_unit", "id")
        )
        dependencies = defaultdict(list)
        operation_ids = {
            order.operation_id for group in groups.values() for order in group
        }
        for dependency in OperationDependency.objects.using(self.database).filter(
            Q(operation_id__in=operation_ids) | Q(blockedby_id__in=operation_ids)
        ):
            dependencies[dependency.operation_id].append(
                (
                    dependency.blockedby_id,
                    timedelta_minutes(
                        dependency.hard_safety_leadtime or dependency.safety_leadtime
                    )
                    or 0,
                )
            )

        steps = []
        for batch_key, group in groups.items():
            task_by_operation = {
                order.operation_id: stable_id("task", order.reference)
                for order in group
            }
            previous_id = None
            for sequence, order in enumerate(group, 1):
                stage = order.operation.mlcc_process_stage
                recipe_value = task_recipes.get(order.reference)
                recipe_object = recipe_value[0] if recipe_value else None
                recipe_id = recipe_value[1] if recipe_value else None
                recipe_resolution = recipe_value[2] if recipe_value else "missing"
                candidate_names = resources_by_operation.get(order.operation_id, ())
                certified = []
                for resource_name in candidate_names:
                    for capability, _ in capabilities:
                        if not capability.enabled:
                            continue
                        if capability.resource_id != resource_name:
                            continue
                        if capability.process_stage != stage:
                            continue
                        if capability.item_id not in (None, order.operation.item_id):
                            continue
                        if capability.recipe_id not in (
                            None,
                            recipe_object.pk if recipe_object else None,
                        ):
                            continue
                        certified.append(resource_name)
                        break

                predecessor_ids = []
                if previous_id:
                    predecessor_ids.append(previous_id)
                predecessor_ids.extend(
                    task_by_operation[operation_id]
                    for operation_id, _ in dependencies.get(order.operation_id, ())
                    if operation_id in task_by_operation
                )
                task_id = stable_id("task", order.reference)
                frozen = order.status in (
                    "approved",
                    "confirmed",
                    "completed",
                    "closed",
                )
                start_minute = self._minute(order.startdate)
                if start_minute is not None and start_minute < self.freeze_hours * 60:
                    frozen = True
                steps.append(
                    ProcessStep(
                        id=task_id,
                        batch_id=stable_id("batch", batch_key),
                        sequence=sequence,
                        stage=stage,
                        operation_id=stable_id("operation", order.operation_id),
                        quantity=order.quantity,
                        duration_minutes=operation_duration_minutes(
                            order.operation.duration,
                            order.operation.duration_per,
                            order.quantity,
                        ),
                        minimum_batch=order.operation.sizeminimum,
                        maximum_batch=order.operation.sizemaximum,
                        candidate_resource_ids=tuple(
                            sorted(
                                stable_id("resource", name) for name in candidate_names
                            )
                        ),
                        certified_resource_ids=tuple(
                            sorted(
                                stable_id("resource", name) for name in set(certified)
                            )
                        ),
                        assigned_resource_id=(
                            stable_id("resource", assigned_resources[order.reference])
                            if order.reference in assigned_resources
                            else None
                        ),
                        recipe_id=recipe_id,
                        predecessor_ids=tuple(sorted(set(predecessor_ids))),
                        minimum_wait_minutes=max(
                            (
                                wait_minutes
                                for operation_id, wait_minutes in dependencies.get(
                                    order.operation_id, ()
                                )
                                if operation_id in task_by_operation
                            ),
                            default=0,
                        ),
                        maximum_wait_minutes=timedelta_minutes(
                            getattr(order.operation, "mlcc_max_wait_time", None)
                        ),
                        started=order.status in ("confirmed", "completed", "closed"),
                        frozen=frozen,
                        original_start_minute=start_minute,
                        original_end_minute=self._minute(order.enddate),
                        recipe_resolution=recipe_resolution,
                        load_requirements=self._load_requirements(
                            order,
                            stage,
                            candidate_names,
                            resource_load_data,
                            conversions,
                        ),
                    )
                )
                previous_id = task_id
        return steps

    @staticmethod
    def _exact_integer(value):
        value = Decimal(value)
        return int(value) if value == value.to_integral_value() else None

    def _load_requirements(
        self,
        order,
        stage,
        candidate_names,
        resource_load_data,
        conversions,
    ):
        if stage not in ("debinding", "sintering"):
            return ()
        source_quantity = (
            getattr(order, "mlcc_load_quantity", None)
            if getattr(order, "mlcc_load_quantity", None) is not None
            else order.quantity
        )
        source_unit = (getattr(order, "mlcc_load_unit", None) or "").strip() or None
        item_id = order.operation.item_id
        requirements = []
        for resource_name in sorted(candidate_names):
            target_unit = resource_load_data.get(resource_name, (None,))[0]
            converted = None
            conversion = None
            if source_unit and target_unit and source_unit == target_unit:
                converted = self._exact_integer(source_quantity)
            elif source_unit and target_unit:
                candidates = [
                    row
                    for row in conversions
                    if row.from_unit == source_unit
                    and row.to_unit == target_unit
                    and row.item_id in (None, item_id)
                ]
                candidates.sort(
                    key=lambda row: (
                        row.item_id != item_id,
                        row.id,
                    )
                )
                if candidates:
                    conversion = candidates[0]
                    converted = self._exact_integer(
                        Decimal(source_quantity)
                        * Decimal(conversion.numerator)
                        / Decimal(conversion.denominator)
                    )
            requirements.append(
                FurnaceLoadRequirement(
                    resource_id=stable_id("resource", resource_name),
                    quantity=converted,
                    load_unit=target_unit,
                    source_quantity=Decimal(source_quantity),
                    source_unit=source_unit,
                    conversion_id=(
                        stable_id("load_conversion", conversion.id)
                        if conversion
                        else (
                            "identity"
                            if source_unit
                            and target_unit
                            and source_unit == target_unit
                            else None
                        )
                    ),
                    conversion_numerator=(
                        conversion.numerator
                        if conversion
                        else (1 if converted is not None else None)
                    ),
                    conversion_denominator=(
                        conversion.denominator
                        if conversion
                        else (1 if converted is not None else None)
                    ),
                )
            )
        return tuple(requirements)

    def _extract_orders_and_batches(self, groups):
        batch_keys = sorted(groups)
        demands = (
            Demand.objects.using(self.database)
            .filter(batch__in=batch_keys)
            .select_related("item")
            .order_by("batch", "priority", "name")
        )
        if self.source:
            demands = demands.filter(source=self.source)
        demand_by_batch = {}
        for demand in demands:
            demand_by_batch.setdefault(demand.batch, demand)

        order_references = [
            order.reference for group in groups.values() for order in group
        ]
        batch_codes = [
            code
            for group in groups.values()
            for order in group
            for code in (order.batch, getattr(order, "mlcc_batch_code", None))
            if code
        ]
        held_orders = set()
        held_codes = set()
        holds = MlccQualityHold.objects.using(self.database).filter(status="active")
        holds = self._source_filter(holds)
        holds = holds.filter(
            Q(manufacturing_order_id__in=order_references)
            | Q(batch_code__in=batch_codes)
        )
        for hold in holds:
            if hold.manufacturing_order_id:
                held_orders.add(hold.manufacturing_order_id)
            held_codes.add(hold.batch_code)

        customer_orders = []
        batches = []
        for batch_key, group in groups.items():
            demand = demand_by_batch.get(batch_key)
            last_order = group[-1]
            item = demand.item if demand else last_order.operation.item
            item_id = stable_id("item", item.pk if item else "unknown")
            quantity = demand.quantity if demand else last_order.quantity
            due = (
                demand.due
                if demand
                else last_order.due or last_order.enddate or last_order.startdate
            )
            priority = demand.priority if demand else 10
            order_id = stable_id(
                "order", demand.name if demand else f"{batch_key}:synthetic"
            )
            batch_id = stable_id("batch", batch_key)
            customer_orders.append(
                CustomerOrder(
                    id=order_id,
                    item_id=item_id,
                    batch_id=batch_id,
                    quantity=quantity,
                    due_minute=self._minute(due),
                    priority=priority,
                )
            )
            quality_hold = any(
                order.reference in held_orders
                or order.batch in held_codes
                or getattr(order, "mlcc_batch_code", None) in held_codes
                for order in group
            )
            batches.append(
                ProductionBatch(
                    id=batch_id,
                    order_id=order_id,
                    item_id=item_id,
                    product_family=(
                        getattr(item, "mlcc_product_family", None) or "" if item else ""
                    ),
                    quantity=quantity,
                    due_minute=self._minute(due),
                    priority=priority,
                    quality_hold=quality_hold,
                    schedulable=all(
                        getattr(order, "mlcc_schedulable", None) is not False
                        for order in group
                    ),
                )
            )
        return customer_orders, batches

    def _extract_materials(self, steps, orders):
        order_by_task = {stable_id("task", order.reference): order for order in orders}
        operation_ids = sorted({order.operation_id for order in orders})
        inputs = defaultdict(list)
        for row in (
            OperationMaterial.objects.using(self.database)
            .filter(operation_id__in=operation_ids, quantity__lt=0)
            .order_by("operation_id", "item_id", "id")
        ):
            inputs[row.operation_id].append(row.item_id)

        required_item_ids = sorted(
            {item for values in inputs.values() for item in values}
        )
        buffers = (
            Buffer.objects.using(self.database)
            .filter(item_id__in=required_item_ids)
            .order_by("item_id", "batch", "location_id", "id")
        )
        buffer_by_item = defaultdict(list)
        for buffer in buffers:
            buffer_by_item[buffer.item_id].append(buffer)

        materials = {}
        for item_id in required_item_ids:
            rows = buffer_by_item.get(item_id, ())
            quantity = sum((row.onhand or Decimal("0") for row in rows), Decimal("0"))
            identifier = stable_id("material", f"{item_id}:*")
            materials[identifier] = MaterialAvailability(
                id=identifier,
                item_id=stable_id("item", item_id),
                batch_id=None,
                quantity=quantity,
                available_minute=0 if quantity > 0 else None,
                kind="raw_material",
            )

        by_batch = defaultdict(list)
        for step in steps:
            by_batch[step.batch_id].append(step)
        updated_steps = []
        for batch_id, batch_steps in by_batch.items():
            batch_steps.sort(key=lambda item: (item.sequence, item.id))
            previous = None
            for step in batch_steps:
                order = order_by_task[step.id]
                required = [
                    stable_id("material", f"{item_id}:*")
                    for item_id in inputs.get(order.operation_id, ())
                ]
                if previous:
                    wip_id = stable_id("wip", f"{batch_id}:{previous.stage}")
                    materials[wip_id] = MaterialAvailability(
                        id=wip_id,
                        item_id=stable_id("item", order.operation.item_id or "unknown"),
                        batch_id=batch_id,
                        quantity=previous.quantity,
                        available_minute=previous.original_end_minute,
                        kind="work_in_progress",
                    )
                    required.append(wip_id)
                updated = replace(
                    step,
                    required_material_ids=tuple(sorted(set(required))),
                )
                updated_steps.append(updated)
                previous = updated
        return updated_steps, list(materials.values())

    def _extract_equipment(self, steps, resources_by_operation, assigned_resources):
        names = {
            name for values in resources_by_operation.values() for name in values
        } | set(assigned_resources.values())
        resources = (
            Resource.objects.using(self.database)
            .filter(name__in=names)
            .select_related("available", "owner")
            .order_by("name")
        )
        return [
            Equipment(
                id=stable_id("resource", resource.name),
                resource_id=resource.name,
                capacity=(
                    getattr(resource, "mlcc_nominal_capacity", None)
                    if getattr(resource, "mlcc_nominal_capacity", None) is not None
                    else resource.maximum
                ),
                load_unit=getattr(resource, "mlcc_load_unit", None),
                equipment_group=(
                    getattr(resource, "mlcc_equipment_group", None) or resource.owner_id
                ),
                **self._calendar_intervals(resource),
            )
            for resource in resources
        ]

    def _extract_frozen_furnace_loads(self, steps):
        task_ids = {item.id for item in steps}
        queryset = (
            MlccFurnaceLoad.objects.using(self.database)
            .filter(Q(frozen=True) | Q(status__in=("ready", "running", "complete")))
            .exclude(status__in=("draft", "proposed", "cancelled"))
            .select_related("resource", "recipe", "furnace_program")
            .prefetch_related("items")
            .order_by("reference")
        )
        queryset = self._source_filter(queryset)
        result = []
        for load in queryset:
            if not load.recipe_id or not load.planned_start or not load.planned_end:
                continue
            member_task_ids = tuple(
                sorted(
                    stable_id("task", row.manufacturing_order_id)
                    for row in load.items.all()
                    if stable_id("task", row.manufacturing_order_id) in task_ids
                )
            )
            capacity = self._exact_integer(load.capacity)
            loaded_quantity = self._exact_integer(load.loaded_quantity)
            result.append(
                FrozenFurnaceLoad(
                    id=stable_id("furnace_load", load.reference),
                    stage=load.operation_type,
                    resource_id=stable_id("resource", load.resource_id),
                    recipe_id=stable_id(
                        "recipe", f"{load.recipe.name}:{load.recipe.version}"
                    ),
                    furnace_program_key=load.furnace_program_key or "",
                    start_minute=self._minute(load.planned_start),
                    end_minute=self._minute(load.planned_end),
                    capacity=-1 if capacity is None else capacity,
                    loaded_quantity=(
                        -1 if loaded_quantity is None else loaded_quantity
                    ),
                    load_unit=load.load_unit,
                    member_task_ids=member_task_ids,
                    status=load.status,
                    furnace_program_id=(
                        stable_id("furnace_program", load.furnace_program_id)
                        if load.furnace_program_id
                        else None
                    ),
                )
            )
        return tuple(result)

    def _extract_furnace_state_snapshots(self, equipment):
        resource_names = sorted(item.resource_id for item in equipment)
        queryset = (
            MlccFurnaceStateSnapshot.objects.using(self.database)
            .filter(
                resource_id__in=resource_names,
                observed_at__lte=self._database_datetime(self.origin),
            )
            .select_related("resource", "current_program")
            .order_by("resource_id", "-observed_at", "-id")
        )
        queryset = self._source_filter(queryset)
        result = []
        seen = set()
        for row in queryset:
            if row.resource_id in seen:
                continue
            seen.add(row.resource_id)
            result.append(
                FurnaceStateSnapshot(
                    id=stable_furnace_state_id(
                        stable_id("resource", row.resource_id),
                        row.observed_at.isoformat(),
                    ),
                    resource_id=stable_id("resource", row.resource_id),
                    observed_minute=self._minute(row.observed_at),
                    state_key=row.state_key,
                    current_program_id=(
                        stable_id("furnace_program", row.current_program_id)
                        if row.current_program_id
                        else None
                    ),
                    available_minute=self._minute(row.available_at),
                    source=row.source,
                )
            )
        return tuple(sorted(result, key=lambda item: item.id))

    def _extract_furnace_transition_rules(self):
        queryset = (
            MlccFurnaceTransitionRule.objects.using(self.database)
            .select_related("resource", "to_program")
            .order_by(
                "process_stage",
                "resource_id",
                "equipment_group",
                "from_state_key",
                "to_program_id",
                "priority",
                "id",
            )
        )
        queryset = self._source_filter(queryset)
        result = []
        for row in queryset:
            resource_id = (
                stable_id("resource", row.resource_id) if row.resource_id else None
            )
            to_program_id = stable_id("furnace_program", row.to_program_id)
            duration_minutes = timedelta_minutes(row.duration) or 0
            effective_date = row.effective_date.isoformat()
            expiry_date = row.expiry_date.isoformat() if row.expiry_date else None
            result.append(
                FurnaceTransitionRule(
                    id=stable_transition_rule_id(
                        resource_id,
                        row.equipment_group,
                        row.process_stage,
                        row.from_state_key,
                        to_program_id,
                        row.transition_type,
                        duration_minutes,
                        row.setup_cost,
                        row.allowed,
                        row.enabled,
                        row.priority,
                        effective_date,
                        expiry_date,
                    ),
                    resource_id=(resource_id),
                    equipment_group=row.equipment_group,
                    stage=row.process_stage,
                    from_state_key=row.from_state_key,
                    to_program_id=to_program_id,
                    transition_type=row.transition_type,
                    duration_minutes=duration_minutes,
                    setup_cost=row.setup_cost,
                    allowed=row.allowed,
                    enabled=row.enabled,
                    priority=row.priority,
                    effective_date=effective_date,
                    expiry_date=expiry_date,
                    scope_level=row.scope_level,
                )
            )
        return tuple(result)

    def _extract_frozen_furnace_transitions(self, frozen_loads):
        load_references = {item.id.split(":", 1)[-1] for item in frozen_loads}
        if not load_references:
            return ()
        queryset = (
            MlccFurnaceTransition.objects.using(self.database)
            .filter(
                successor_load__reference__in=load_references,
                run_id=F("successor_load__run_id"),
            )
            .select_related(
                "resource",
                "predecessor_load",
                "successor_load",
                "transition_rule",
            )
            .order_by("resource_id", "planned_start", "id")
        )
        queryset = self._source_filter(queryset)
        return tuple(
            FrozenFurnaceTransition(
                id=stable_furnace_transition_id(
                    stable_id("resource", row.resource_id),
                    (
                        stable_id("furnace_load", row.predecessor_load.reference)
                        if row.predecessor_load_id
                        else None
                    ),
                    stable_id("furnace_load", row.successor_load.reference),
                ),
                resource_id=stable_id("resource", row.resource_id),
                predecessor_load_id=(
                    stable_id("furnace_load", row.predecessor_load.reference)
                    if row.predecessor_load_id
                    else None
                ),
                successor_load_id=stable_id(
                    "furnace_load", row.successor_load.reference
                ),
                transition_rule_id=stable_transition_rule_id(
                    (
                        stable_id("resource", row.transition_rule.resource_id)
                        if row.transition_rule.resource_id
                        else None
                    ),
                    row.transition_rule.equipment_group,
                    row.transition_rule.process_stage,
                    row.transition_rule.from_state_key,
                    stable_id(
                        "furnace_program",
                        row.transition_rule.to_program_id,
                    ),
                    row.transition_rule.transition_type,
                    timedelta_minutes(row.transition_rule.duration) or 0,
                    row.transition_rule.setup_cost,
                    row.transition_rule.allowed,
                    row.transition_rule.enabled,
                    row.transition_rule.priority,
                    row.transition_rule.effective_date.isoformat(),
                    (
                        row.transition_rule.expiry_date.isoformat()
                        if row.transition_rule.expiry_date
                        else None
                    ),
                ),
                transition_type=row.transition_type,
                start_minute=self._minute(row.planned_start),
                end_minute=self._minute(row.planned_end),
                status=row.status,
            )
            for row in queryset
        )

    def _calendar_intervals(self, resource):
        horizon = self.horizon_days * 24 * 60
        if not resource.available_id:
            return {
                "shifts": (CalendarInterval(0, horizon, "shift"),),
                "downtimes": (),
                "maintenance": (),
            }
        calendar = resource.available
        buckets = list(
            CalendarBucket.objects.using(self.database)
            .filter(calendar_id=calendar.pk)
            .order_by("priority", "startdate", "enddate", "id")
        )
        if not buckets:
            kind = "shift" if (calendar.defaultvalue or 0) > 0 else "downtime"
            return {
                "shifts": (
                    (CalendarInterval(0, horizon, kind),) if kind == "shift" else ()
                ),
                "downtimes": (
                    (CalendarInterval(0, horizon, kind),) if kind == "downtime" else ()
                ),
                "maintenance": (),
            }
        result = {"shifts": [], "downtimes": [], "maintenance": []}
        current_date = self.origin.date()
        end_date = self.horizon_end.date()
        while current_date <= end_date:
            for bucket in buckets:
                weekday_name = (
                    "monday",
                    "tuesday",
                    "wednesday",
                    "thursday",
                    "friday",
                    "saturday",
                    "sunday",
                )[current_date.weekday()]
                if not getattr(bucket, weekday_name):
                    continue
                start_limit = (
                    self._normalize_datetime(bucket.startdate)
                    if bucket.startdate
                    else self.origin
                )
                end_limit = (
                    self._normalize_datetime(bucket.enddate)
                    if bucket.enddate
                    else self.horizon_end
                )
                start_time = bucket.starttime or time.min
                end_time = bucket.endtime or time.max
                start = datetime.combine(current_date, start_time, self.zone)
                end = datetime.combine(current_date, end_time, self.zone)
                if end <= start:
                    end += timedelta(days=1)
                if start < start_limit or start >= end_limit:
                    continue
                start_minute = max(0, self._minute(start))
                end_minute = min(horizon, self._minute(end))
                if end_minute <= start_minute:
                    continue
                if "maintenance" in (bucket.source or "").lower():
                    key = "maintenance"
                    kind = "maintenance"
                elif (bucket.value or 0) > 0:
                    key = "shifts"
                    kind = "shift"
                else:
                    key = "downtimes"
                    kind = "downtime"
                result[key].append(CalendarInterval(start_minute, end_minute, kind))
            current_date += timedelta(days=1)
        return {
            key: tuple(
                sorted(value, key=lambda item: (item.start_minute, item.end_minute))
            )
            for key, value in result.items()
        }

    def _extract_compatibility_rules(self):
        queryset = MlccCompatibilityRule.objects.using(self.database).order_by(
            "process_stage", "family_a", "family_b", "rule_type", "name"
        )
        queryset = self._source_filter(queryset)
        result = [
            CompatibilityRule(
                id=stable_id("compatibility", row.name),
                stage=row.process_stage,
                family_a=row.family_a,
                family_b=row.family_b,
                rule_type=row.rule_type,
                enabled=row.enabled,
            )
            for row in queryset
        ]
        return tuple(sorted(result, key=lambda item: item.id))

    def _extract_setup_rules(self):
        queryset = (
            MlccSetupMatrix.objects.using(self.database)
            .select_related("from_recipe", "to_recipe")
            .order_by("resource_id", "process_stage", "from_recipe_id", "to_recipe_id")
        )
        queryset = self._source_filter(queryset)
        result = []
        for row in queryset:
            from_id = stable_id(
                "recipe", f"{row.from_recipe.name}:{row.from_recipe.version}"
            )
            to_id = stable_id("recipe", f"{row.to_recipe.name}:{row.to_recipe.version}")
            result.append(
                SetupRule(
                    id=stable_id(
                        "setup",
                        f"{row.resource_id or '*'}:{row.process_stage}:{from_id}:{to_id}",
                    ),
                    resource_id=(
                        stable_id("resource", row.resource_id)
                        if row.resource_id
                        else None
                    ),
                    stage=row.process_stage,
                    from_recipe_id=from_id,
                    to_recipe_id=to_id,
                    duration_minutes=timedelta_minutes(row.setup_time) or 0,
                )
            )
        return tuple(sorted(result, key=lambda item: item.id))
