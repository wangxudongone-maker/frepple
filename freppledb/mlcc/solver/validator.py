"""Pure, solver-independent validation of an MLCC planning instance."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .reasons import PrecheckIssue, issue
from .schema import PROCESS_STAGE_ORDER, PlanningInstance
from .transition_rules import resolve_transition_rule, rule_is_effective


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
        self._validate_furnace_programs()
        self._validate_initial_furnace_states()
        self._validate_transition_rules()
        self._validate_transition_reachability()
        self._validate_furnaces_and_batches()
        self._validate_compatibility()
        self._validate_dependencies()
        self._validate_quality_holds()
        self._validate_frozen_tasks()
        self._validate_frozen_furnace_loads()
        self._validate_frozen_furnace_transitions()
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
            if step.recipe_resolution == "ambiguous":
                self._add("AMBIGUOUS_FURNACE_PROGRAM", "task", step.id)
                continue
            if not step.recipe_id or step.recipe_id not in recipes:
                self._add("MISSING_RECIPE", "task", step.id)
                continue
            recipe = recipes[step.recipe_id]
            if not (recipe.furnace_program_key or "").strip():
                self._add("AMBIGUOUS_FURNACE_PROGRAM", "task", step.id)
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

    def _validate_furnace_programs(self):
        programs = {item.id: item for item in self.instance.furnace_programs}
        origin_date = date.fromisoformat(self.instance.window.origin[:10])
        identities = defaultdict(list)
        for program in self.instance.furnace_programs:
            identities[(program.program_key, program.version)].append(program.id)
        for ids in identities.values():
            if len(ids) > 1:
                self._add(
                    "FURNACE_PROGRAM_MAPPING_INVALID",
                    "furnace_program",
                    ",".join(sorted(ids)),
                    "炉程业务键和版本重复。",
                )

        recipes = {item.id: item for item in self.instance.recipes}
        for step in self.instance.steps:
            if step.stage not in ("debinding", "sintering") or not step.recipe_id:
                continue
            recipe = recipes.get(step.recipe_id)
            program = programs.get(recipe.furnace_program_id) if recipe else None
            invalid = (
                recipe is None
                or not recipe.furnace_program_id
                or program is None
                or program.stage != step.stage
                or recipe.stage != program.stage
                or recipe.furnace_program_key != program.program_key
            )
            if program:
                try:
                    effective = date.fromisoformat(program.effective_date)
                    expiry = (
                        date.fromisoformat(program.expiry_date)
                        if program.expiry_date
                        else None
                    )
                except (TypeError, ValueError):
                    invalid = True
                else:
                    invalid = invalid or (
                        not program.active
                        or effective > origin_date
                        or (expiry is not None and expiry < origin_date)
                    )
            if invalid:
                self._add(
                    "FURNACE_PROGRAM_MAPPING_INVALID",
                    "task",
                    step.id,
                )

    def _furnace_resource_ids(self):
        return {
            resource_id
            for step in self.instance.steps
            if step.stage in ("debinding", "sintering")
            for resource_id in step.certified_resource_ids
        }

    def _validate_initial_furnace_states(self):
        snapshots = defaultdict(list)
        for state in self.instance.furnace_state_snapshots:
            snapshots[state.resource_id].append(state)
        for resource_id in sorted(self._furnace_resource_ids()):
            candidates = snapshots.get(resource_id, ())
            valid = [
                state
                for state in candidates
                if state.observed_minute <= 0
                and state.available_minute >= state.observed_minute
                and (state.state_key or "").strip()
            ]
            if len(valid) != 1:
                self._add(
                    "INITIAL_FURNACE_STATE_INVALID",
                    "resource",
                    resource_id,
                    ("同一排产起点存在多个最新状态。" if len(valid) > 1 else None),
                )

    def _validate_transition_rules(self):
        programs = {item.id: item for item in self.instance.furnace_programs}
        equipment = {item.id: item for item in self.instance.equipment}
        origin_date = date.fromisoformat(self.instance.window.origin[:10])
        active_by_resolution_key = defaultdict(list)
        for rule in self.instance.furnace_transition_rules:
            invalid = (
                rule.duration_minutes < 0
                or rule.setup_cost < 0
                or rule.scope_level not in ("resource", "equipment_group", "global")
                or (rule.resource_id and rule.equipment_group)
                or (rule.resource_id and rule.resource_id not in equipment)
            )
            program = programs.get(rule.to_program_id)
            invalid = (
                invalid
                or program is None
                or (program is not None and program.stage != rule.stage)
            )
            if rule.enabled and not rule_is_effective(rule, origin_date):
                try:
                    effective = date.fromisoformat(rule.effective_date)
                    expiry = (
                        date.fromisoformat(rule.expiry_date)
                        if rule.expiry_date
                        else None
                    )
                    invalid = invalid or (expiry is not None and expiry < effective)
                except (TypeError, ValueError):
                    invalid = True
            if invalid:
                self._add(
                    "TRANSITION_RULE_INVALID",
                    "furnace_transition_rule",
                    rule.id,
                )
            if rule_is_effective(rule, origin_date):
                scope = (
                    f"resource:{rule.resource_id}"
                    if rule.resource_id
                    else (
                        f"group:{rule.equipment_group}"
                        if rule.equipment_group
                        else "global"
                    )
                )
                active_by_resolution_key[
                    (
                        scope,
                        rule.stage,
                        rule.from_state_key,
                        rule.to_program_id,
                        rule.priority,
                    )
                ].append(rule.id)
        for ids in active_by_resolution_key.values():
            if len(ids) > 1:
                self._add(
                    "TRANSITION_RULE_INVALID",
                    "furnace_transition_rule",
                    ",".join(sorted(ids)),
                    "同一层级和优先级存在多条有效规则。",
                )

    def _validate_transition_reachability(self):
        programs = {item.id: item for item in self.instance.furnace_programs}
        recipes = {item.id: item for item in self.instance.recipes}
        states = {
            item.resource_id: item for item in self.instance.furnace_state_snapshots
        }
        used_programs = {
            recipe.furnace_program_id
            for step in self.instance.steps
            if step.stage in ("debinding", "sintering") and step.recipe_id
            for recipe in (recipes.get(step.recipe_id),)
            if recipe and recipe.furnace_program_id in programs
        }
        predecessor_states = {
            programs[program_id].resulting_post_state_key
            for program_id in used_programs
        }
        reported_conflicts = set()
        for step in self.instance.steps:
            if step.stage not in ("debinding", "sintering") or not step.recipe_id:
                continue
            recipe = recipes.get(step.recipe_id)
            program_id = recipe.furnace_program_id if recipe else None
            if program_id not in programs:
                continue
            reachable = False
            for resource_id in sorted(step.certified_resource_ids):
                from_states = set(predecessor_states)
                if resource_id in states:
                    from_states.add(states[resource_id].state_key)
                for from_state in sorted(from_states):
                    resolution = resolve_transition_rule(
                        self.instance,
                        resource_id,
                        step.stage,
                        from_state,
                        program_id,
                    )
                    if resolution.conflict:
                        key = tuple(resolution.candidate_rule_ids)
                        if key not in reported_conflicts:
                            reported_conflicts.add(key)
                            self._add(
                                "TRANSITION_RULE_INVALID",
                                "furnace_transition_rule",
                                ",".join(key),
                            )
                    elif resolution.allowed:
                        reachable = True
                        break
                if reachable:
                    break
            if not reachable:
                self._add(
                    "FURNACE_PROGRAM_UNREACHABLE",
                    "task",
                    step.id,
                )

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
            requirements = {item.resource_id: item for item in step.load_requirements}
            exact = [
                (resource, requirements.get(resource.id))
                for resource in candidates
                if requirements.get(resource.id) is not None
                and requirements[resource.id].quantity is not None
                and requirements[resource.id].quantity > 0
                and requirements[resource.id].load_unit == resource.load_unit
            ]
            if candidates and not exact:
                self._add("INEXACT_LOAD_CONVERSION", "task", step.id)
            elif exact and not any(
                resource.capacity is not None
                and resource.capacity == resource.capacity.to_integral_value()
                and requirement.quantity <= int(resource.capacity)
                for resource, requirement in exact
            ):
                self._add("BATCH_EXCEEDS_ALL_FURNACES", "task", step.id)

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

    def _validate_frozen_furnace_loads(self):
        steps = {item.id: item for item in self.instance.steps}
        equipment = {item.id: item for item in self.instance.equipment}
        recipes = {item.id: item for item in self.instance.recipes}
        seen_members = set()
        for load in self.instance.frozen_furnace_loads:
            invalid = False
            resource = equipment.get(load.resource_id)
            recipe = recipes.get(load.recipe_id)
            members = [steps.get(item) for item in load.member_task_ids]
            if (
                resource is None
                or recipe is None
                or recipe.furnace_program_key != load.furnace_program_key
                or recipe.stage != load.stage
                or resource.capacity is None
                or resource.capacity != resource.capacity.to_integral_value()
                or int(resource.capacity) != load.capacity
                or resource.load_unit != load.load_unit
                or load.end_minute <= load.start_minute
                or not members
                or any(item is None for item in members)
            ):
                invalid = True
            total = 0
            for step in (item for item in members if item is not None):
                requirement = next(
                    (
                        item
                        for item in step.load_requirements
                        if item.resource_id == load.resource_id
                    ),
                    None,
                )
                if (
                    step.id in seen_members
                    or step.stage != load.stage
                    or step.recipe_id != load.recipe_id
                    or step.assigned_resource_id != load.resource_id
                    or step.original_start_minute != load.start_minute
                    or step.original_end_minute != load.end_minute
                    or not (step.frozen or step.started)
                    or requirement is None
                    or requirement.quantity is None
                    or requirement.load_unit != load.load_unit
                ):
                    invalid = True
                else:
                    total += requirement.quantity
                seen_members.add(step.id)
            if total != load.loaded_quantity or total > load.capacity:
                invalid = True
            if invalid:
                self._add("FROZEN_LOAD_MISMATCH", "furnace_load", load.id)

    def _validate_frozen_furnace_transitions(self):
        loads = {item.id: item for item in self.instance.frozen_furnace_loads}
        transitions_by_successor = defaultdict(list)
        for transition in self.instance.frozen_furnace_transitions:
            transitions_by_successor[transition.successor_load_id].append(transition)
        rules = {item.id: item for item in self.instance.furnace_transition_rules}
        programs = {item.id: item for item in self.instance.furnace_programs}
        recipes = {item.id: item for item in self.instance.recipes}
        states = {
            item.resource_id: item for item in self.instance.furnace_state_snapshots
        }
        graph = {}
        for load_id, load in loads.items():
            incoming = transitions_by_successor.get(load_id, ())
            if len(incoming) != 1:
                self._add(
                    "FROZEN_TRANSITION_MISMATCH",
                    "furnace_load",
                    load_id,
                )
                continue
            transition = incoming[0]
            rule = rules.get(transition.transition_rule_id)
            recipe = recipes.get(load.recipe_id) if load.recipe_id else None
            program_id = load.furnace_program_id or (
                recipe.furnace_program_id if recipe else None
            )
            predecessor = (
                loads.get(transition.predecessor_load_id)
                if transition.predecessor_load_id
                else None
            )
            from_state = None
            predecessor_ready = 0
            if predecessor:
                predecessor_recipe = (
                    recipes.get(predecessor.recipe_id)
                    if predecessor.recipe_id
                    else None
                )
                predecessor_program_id = predecessor.furnace_program_id or (
                    predecessor_recipe.furnace_program_id
                    if predecessor_recipe
                    else None
                )
                predecessor_program = programs.get(predecessor_program_id)
                from_state = (
                    predecessor_program.resulting_post_state_key
                    if predecessor_program
                    else None
                )
                predecessor_ready = predecessor.end_minute
                graph[load_id] = predecessor.id
            else:
                state = states.get(load.resource_id)
                from_state = state.state_key if state else None
                predecessor_ready = state.available_minute if state else 0

            invalid = (
                transition.resource_id != load.resource_id
                or transition.status != "proposed"
                or transition.end_minute < transition.start_minute
                or transition.end_minute > load.start_minute
                or transition.start_minute < predecessor_ready
                or load.predecessor_load_id != transition.predecessor_load_id
                or rule is None
                or not rule.allowed
                or not rule.enabled
                or rule.transition_type != transition.transition_type
                or transition.end_minute - transition.start_minute
                != (rule.duration_minutes if rule else -1)
                or from_state is None
                or program_id is None
            )
            if not invalid:
                resolution = resolve_transition_rule(
                    self.instance,
                    load.resource_id,
                    load.stage,
                    from_state,
                    program_id,
                )
                invalid = (
                    resolution.conflict
                    or not resolution.allowed
                    or resolution.rule.id != transition.transition_rule_id
                )
            if invalid:
                self._add(
                    "FROZEN_TRANSITION_MISMATCH",
                    "furnace_transition",
                    transition.id,
                )

        for transition in self.instance.frozen_furnace_transitions:
            if transition.successor_load_id not in loads:
                self._add(
                    "FROZEN_TRANSITION_MISMATCH",
                    "furnace_transition",
                    transition.id,
                )
        for load_id in sorted(graph):
            seen = set()
            current = load_id
            while current in graph:
                if current in seen:
                    self._add(
                        "FROZEN_TRANSITION_MISMATCH",
                        "furnace_load",
                        load_id,
                        "冻结炉次顺序形成循环。",
                    )
                    break
                seen.add(current)
                current = graph[current]

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
