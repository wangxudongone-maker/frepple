"""Pure, solver-independent validation of an MLCC planning instance."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .reasons import PrecheckIssue, issue
from .schema import PROCESS_STAGE_ORDER, PlanningInstance


@dataclass(frozen=True)
class PrecheckReport:
    issues: tuple[PrecheckIssue, ...]

    @property
    def blocker_count(self):
        return sum(item.severity == "BLOCKER" for item in self.issues)

    @property
    def warning_count(self):
        return sum(item.severity == "WARNING" for item in self.issues)

    @property
    def info_count(self):
        return sum(item.severity == "INFO" for item in self.issues)

    @property
    def can_start_solver(self):
        return self.blocker_count == 0

    @property
    def summary(self):
        return {
            "BLOCKER": self.blocker_count,
            "WARNING": self.warning_count,
            "INFO": self.info_count,
            "can_start_solver": self.can_start_solver,
        }


class PlanningInstanceValidator:
    """Validate only schema values and never access Django ORM objects."""

    def validate(self, instance: PlanningInstance):
        self.instance = instance
        self.issues = []
        self._validate_routings()
        self._validate_standard_times()
        self._validate_resources_and_capabilities()
        self._validate_recipes()
        self._validate_furnaces_and_batches()
        self._validate_compatibility()
        self._validate_dependencies()
        self._validate_quality_holds()
        self._validate_frozen_tasks()
        self._validate_materials()
        self._validate_quantities()
        self._validate_waiting_times()
        self._validate_horizon()

        severity_order = {"BLOCKER": 0, "WARNING": 1, "INFO": 2}
        unique = {
            (
                item.code,
                item.severity,
                item.object_type,
                item.object_id,
                item.source_field,
            ): item
            for item in self.issues
        }
        ordered = sorted(
            unique.values(),
            key=lambda item: (
                severity_order[item.severity],
                item.code,
                item.object_type,
                item.object_id,
                item.source_field,
            ),
        )
        return PrecheckReport(tuple(ordered))

    def _add(self, reason_key, object_type, object_id, detail=None):
        self.issues.append(issue(reason_key, object_type, object_id, detail))

    def _validate_routings(self):
        by_batch = defaultdict(list)
        for step in self.instance.steps:
            by_batch[step.batch_id].append(step)
        expected = set(PROCESS_STAGE_ORDER)
        for batch in self.instance.batches:
            batch_steps = sorted(
                by_batch.get(batch.id, ()), key=lambda item: (item.sequence, item.id)
            )
            stages = {step.stage for step in batch_steps}
            missing = [stage for stage in PROCESS_STAGE_ORDER if stage not in stages]
            actual_order = tuple(step.stage for step in batch_steps)
            if (
                missing
                or stages - expected
                or len(batch_steps) != len(PROCESS_STAGE_ORDER)
                or actual_order != PROCESS_STAGE_ORDER
            ):
                detail = "缺少：" + "、".join(missing) if missing else None
                self._add("MISSING_ROUTING", "production_batch", batch.id, detail)

    def _validate_standard_times(self):
        for step in self.instance.steps:
            if step.duration_minutes <= 0:
                self._add("INVALID_STANDARD_TIME", "task", step.id)

    def _validate_resources_and_capabilities(self):
        capability_ids = {
            item.id for item in self.instance.capabilities if item.enabled
        }
        capabilities_by_resource_stage = defaultdict(list)
        for capability in self.instance.capabilities:
            if capability.enabled:
                capabilities_by_resource_stage[
                    (capability.resource_id, capability.stage)
                ].append(capability)

        for step in self.instance.steps:
            if not step.candidate_resource_ids:
                self._add("NO_AVAILABLE_RESOURCE", "task", step.id)
                continue
            valid_resources = {
                resource_id
                for resource_id in step.certified_resource_ids
                if any(
                    capability.id in capability_ids
                    and (
                        capability.minimum_quantity is None
                        or step.quantity >= capability.minimum_quantity
                    )
                    and (
                        capability.maximum_quantity is None
                        or step.quantity <= capability.maximum_quantity
                    )
                    for capability in capabilities_by_resource_stage.get(
                        (resource_id, step.stage), ()
                    )
                )
            }
            if not valid_resources:
                self._add("MISSING_CAPABILITY", "task", step.id)

    def _validate_recipes(self):
        recipes = {recipe.id: recipe for recipe in self.instance.recipes}
        origin_date = date.fromisoformat(self.instance.window.origin[:10])
        for step in self.instance.steps:
            if step.stage not in ("debinding", "sintering"):
                continue
            if not step.recipe_id or step.recipe_id not in recipes:
                self._add("MISSING_RECIPE", "task", step.id)
                continue
            recipe = recipes[step.recipe_id]
            effective = date.fromisoformat(recipe.effective_date)
            expiry = (
                date.fromisoformat(recipe.expiry_date) if recipe.expiry_date else None
            )
            if (
                not recipe.active
                or effective > origin_date
                or (expiry is not None and expiry < origin_date)
            ):
                self._add("INVALID_RECIPE", "recipe", recipe.id)

    def _validate_furnaces_and_batches(self):
        equipment = {item.id: item for item in self.instance.equipment}
        for step in self.instance.steps:
            if step.quantity <= 0:
                self._add("INVALID_BATCH_OR_LOAD_UNIT", "task", step.id)
            if step.minimum_batch is not None and step.quantity < step.minimum_batch:
                self._add("INVALID_BATCH_OR_LOAD_UNIT", "task", step.id)
            if step.maximum_batch is not None and step.quantity > step.maximum_batch:
                self._add("INVALID_BATCH_OR_LOAD_UNIT", "task", step.id)
            if step.stage not in ("debinding", "sintering"):
                continue
            candidates = [
                equipment[resource_id]
                for resource_id in step.certified_resource_ids
                if resource_id in equipment
            ]
            if candidates and not any(
                resource.capacity is not None and resource.capacity > 0
                for resource in candidates
            ):
                self._add("INVALID_FURNACE_CAPACITY", "task", step.id)
            if candidates and not any(
                (resource.load_unit or "").strip() for resource in candidates
            ):
                self._add("INVALID_BATCH_OR_LOAD_UNIT", "task", step.id)

    def _validate_compatibility(self):
        rules = defaultdict(set)
        ids = defaultdict(list)
        for rule in self.instance.compatibility_rules:
            if not rule.enabled:
                continue
            pair = tuple(sorted((rule.family_a.strip(), rule.family_b.strip())))
            key = (rule.stage, *pair)
            rules[key].add(rule.rule_type)
            ids[key].append(rule.id)
        for key, rule_types in rules.items():
            if len(rule_types) > 1:
                self._add(
                    "COMPATIBILITY_CONFLICT",
                    "compatibility_rule",
                    ",".join(sorted(ids[key])),
                )

    def _validate_dependencies(self):
        graph = {step.id: set(step.predecessor_ids) for step in self.instance.steps}
        visiting = set()
        path = []
        visited = set()
        cyclic = set()

        def visit(node):
            if node in visiting:
                cyclic.update(path[path.index(node) :])
                return
            if node in visited:
                return
            visiting.add(node)
            path.append(node)
            for predecessor in graph.get(node, ()):
                if predecessor in graph:
                    visit(predecessor)
            path.pop()
            visiting.remove(node)
            visited.add(node)

        for node in sorted(graph):
            visit(node)
        for node in sorted(cyclic):
            self._add("DEPENDENCY_CYCLE", "task", node)

    def _validate_quality_holds(self):
        for batch in self.instance.batches:
            if batch.quality_hold and batch.schedulable:
                self._add("HELD_BATCH_SCHEDULABLE", "production_batch", batch.id)

    @staticmethod
    def _overlaps(start, end, interval):
        return start < interval.end_minute and end > interval.start_minute

    def _validate_frozen_tasks(self):
        equipment = {item.id: item for item in self.instance.equipment}
        for step in self.instance.steps:
            if not (step.frozen or step.started):
                continue
            if (
                not step.assigned_resource_id
                or step.original_start_minute is None
                or step.original_end_minute is None
            ):
                continue
            resource = equipment.get(step.assigned_resource_id)
            if not resource:
                continue
            unavailable = resource.downtimes + resource.maintenance
            if any(
                self._overlaps(
                    step.original_start_minute,
                    step.original_end_minute,
                    interval,
                )
                for interval in unavailable
            ):
                self._add("FROZEN_DOWNTIME_CONFLICT", "task", step.id)

    def _validate_materials(self):
        materials = {item.id: item for item in self.instance.materials}
        for step in self.instance.steps:
            for material_id in step.required_material_ids:
                material = materials.get(material_id)
                if material is None or material.available_minute is None:
                    self._add(
                        "MATERIAL_AVAILABILITY_MISSING",
                        "task",
                        step.id,
                        f"物料 {material_id}",
                    )

    def _validate_quantities(self):
        steps_by_batch = defaultdict(list)
        for step in self.instance.steps:
            steps_by_batch[step.batch_id].append(step)
        for batch in self.instance.batches:
            if batch.quantity <= 0:
                self._add("QUANTITY_IMBALANCE", "production_batch", batch.id)
                continue
            quantities = [step.quantity for step in steps_by_batch.get(batch.id, ())]
            if quantities and any(
                quantity != batch.quantity for quantity in quantities
            ):
                self._add("QUANTITY_IMBALANCE", "production_batch", batch.id)
        orders = {item.id: item for item in self.instance.customer_orders}
        batch_totals = defaultdict(lambda: Decimal("0"))
        for batch in self.instance.batches:
            batch_totals[batch.order_id] += batch.quantity
        for order_id, order in orders.items():
            if batch_totals[order_id] != order.quantity:
                self._add("QUANTITY_IMBALANCE", "customer_order", order_id)

    def _validate_waiting_times(self):
        for step in self.instance.steps:
            if step.maximum_wait_minutes is None:
                continue
            if step.maximum_wait_minutes < step.minimum_wait_minutes:
                self._add("MAX_WAIT_TOO_SHORT", "task", step.id)

    def _validate_horizon(self):
        horizon = self.instance.window.horizon_minutes
        for order in self.instance.customer_orders:
            if order.due_minute is None or not 0 <= order.due_minute <= horizon:
                self._add("OUTSIDE_HORIZON", "customer_order", order.id)
        for step in self.instance.steps:
            values = (step.original_start_minute, step.original_end_minute)
            if any(value is not None and not 0 <= value <= horizon for value in values):
                self._add("OUTSIDE_HORIZON", "task", step.id)
