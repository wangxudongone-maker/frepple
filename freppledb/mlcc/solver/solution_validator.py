"""Independent validation of schedule output without invoking CP-SAT."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from .constraints import (
    FURNACE_STAGES,
    available_segments,
    capability_index,
    eligible_resources,
    load_requirement,
    material_ready_minute,
    schedulable_steps,
)
from .transition_rules import resolve_transition_rule, transition_rule_snapshot


@dataclass(frozen=True)
class SolutionViolation:
    code: str
    object_id: str
    message: str


@dataclass(frozen=True)
class SolutionValidationReport:
    violations: tuple[SolutionViolation, ...]

    @property
    def violation_count(self):
        return len(self.violations)

    @property
    def valid(self):
        return not self.violations


class SchedulingSolutionValidator:
    """Validate phase-3B hard constraints using data only."""

    def validate(self, instance, solution):
        violations = []

        def add(code, object_id, message):
            violations.append(SolutionViolation(code, object_id, message))

        if solution.input_fingerprint == "":
            add("MLCC-SV001", "solution", "Missing input fingerprint.")
        if solution.status not in ("FEASIBLE", "OPTIMAL"):
            add(
                "MLCC-SV002",
                "solution",
                f"Solution status {solution.status} has no schedulable result.",
            )

        steps = {item.id: item for item in schedulable_steps(instance)}
        equipment = {item.id: item for item in instance.equipment}
        assignments = {}
        for assignment in solution.assignments:
            if assignment.task_id in assignments:
                add(
                    "MLCC-SV003",
                    assignment.task_id,
                    "Task has more than one assignment.",
                )
            assignments[assignment.task_id] = assignment
        for task_id in sorted(set(steps) - set(assignments)):
            add("MLCC-SV004", task_id, "Task is not assigned.")
        for task_id in sorted(set(assignments) - set(steps)):
            add("MLCC-SV005", task_id, "Assignment references an unknown task.")

        indexed_capabilities = capability_index(instance)
        by_resource = defaultdict(list)
        for task_id in sorted(set(steps) & set(assignments)):
            step = steps[task_id]
            assignment = assignments[task_id]
            resource = equipment.get(assignment.resource_id)
            if assignment.resource_id not in eligible_resources(
                instance, step, indexed_capabilities
            ):
                add(
                    "MLCC-SV006",
                    task_id,
                    "Assigned resource is not eligible and certified.",
                )
            if (
                assignment.start_minute < 0
                or assignment.end_minute > instance.window.horizon_minutes
                or assignment.end_minute <= assignment.start_minute
            ):
                add(
                    "MLCC-SV007",
                    task_id,
                    "Assignment is outside the planning horizon.",
                )
            if assignment.end_minute - assignment.start_minute != step.duration_minutes:
                add(
                    "MLCC-SV008",
                    task_id,
                    "Assignment duration differs from standard duration.",
                )
            if resource and not any(
                start <= assignment.start_minute and assignment.end_minute <= end
                for start, end in available_segments(
                    resource, instance.window.horizon_minutes
                )
            ):
                add(
                    "MLCC-SV009",
                    task_id,
                    "Assignment is outside shifts or overlaps downtime/maintenance.",
                )
            if assignment.start_minute < material_ready_minute(instance, step):
                add(
                    "MLCC-SV010",
                    task_id,
                    "Task starts before material or WIP availability.",
                )
            if step.frozen or step.started:
                if (
                    assignment.resource_id != step.assigned_resource_id
                    or assignment.start_minute != step.original_start_minute
                    or assignment.end_minute != step.original_end_minute
                ):
                    add(
                        "MLCC-SV011",
                        task_id,
                        "Frozen or started task was moved.",
                    )
            by_resource[assignment.resource_id].append(assignment)

        for resource_id, resource_assignments in by_resource.items():
            distinct = {}
            for item in resource_assignments:
                key = item.furnace_load_id or f"task:{item.task_id}"
                distinct.setdefault(key, item)
            ordered = sorted(
                distinct.values(),
                key=lambda item: (item.start_minute, item.end_minute, item.task_id),
            )
            for previous, current in zip(ordered, ordered[1:]):
                if previous.end_minute > current.start_minute:
                    add(
                        "MLCC-SV012",
                        resource_id,
                        f"Tasks {previous.task_id} and {current.task_id} overlap.",
                    )

        batches = {item.id: item for item in instance.batches}
        recipes = {item.id: item for item in instance.recipes}
        loads = {}
        for load in solution.furnace_loads:
            if load.load_id in loads:
                add(
                    "MLCC-SV017", load.load_id, "Furnace load identifier is duplicated."
                )
            loads[load.load_id] = load
        furnace_task_ids = {
            item.id for item in steps.values() if item.stage in FURNACE_STAGES
        }
        for task_id in sorted(furnace_task_ids):
            assignment = assignments.get(task_id)
            if assignment is None or not assignment.furnace_load_id:
                add("MLCC-SV018", task_id, "Furnace task has no explicit furnace load.")
            elif assignment.furnace_load_id not in loads:
                add("MLCC-SV019", task_id, "Furnace task references an unknown load.")
            elif task_id not in loads[assignment.furnace_load_id].member_task_ids:
                add(
                    "MLCC-SV022",
                    task_id,
                    "Furnace task is absent from its referenced load membership.",
                )

        frozen = {item.id: item for item in instance.frozen_furnace_loads}
        for load_id, load in sorted(loads.items()):
            member_ids = tuple(sorted(load.member_task_ids))
            if not member_ids:
                add("MLCC-SV020", load_id, "Furnace load has no members.")
                continue
            member_assignments = [assignments.get(item) for item in member_ids]
            if any(item is None for item in member_assignments):
                add("MLCC-SV021", load_id, "Furnace load references an unknown task.")
                continue
            if any(
                item.furnace_load_id != load_id
                or item.resource_id != load.equipment_id
                or item.start_minute != load.start_minute
                or item.end_minute != load.end_minute
                for item in member_assignments
            ):
                add("MLCC-SV022", load_id, "Furnace members are not synchronized.")
            member_steps = [steps[item] for item in member_ids]
            if any(item.stage != load.operation_type for item in member_steps):
                add("MLCC-SV023", load_id, "Furnace load mixes operation types.")
            if any(
                recipes[item.recipe_id].furnace_program_key != load.furnace_program_key
                for item in member_steps
            ):
                add("MLCC-SV024", load_id, "Furnace load mixes executable programs.")
            requirements = [
                load_requirement(item, load.equipment_id) for item in member_steps
            ]
            if any(
                item is None
                or item.quantity is None
                or item.load_unit != load.load_unit
                for item in requirements
            ):
                add("MLCC-SV025", load_id, "Load conversion is missing or inexact.")
            else:
                expected = sum(item.quantity for item in requirements)
                if (
                    expected != load.loaded_quantity
                    or load.loaded_quantity > load.capacity
                    or load.capacity <= 0
                ):
                    add("MLCC-SV026", load_id, "Furnace capacity is violated.")
            for index, left in enumerate(member_steps):
                for right in member_steps[index + 1 :]:
                    left_recipe = recipes[left.recipe_id]
                    right_recipe = recipes[right.recipe_id]
                    pair = tuple(
                        sorted(
                            (
                                batches[left.batch_id].product_family.strip(),
                                batches[right.batch_id].product_family.strip(),
                            )
                        )
                    )
                    matches = [
                        rule
                        for rule in instance.compatibility_rules
                        if rule.enabled
                        and rule.stage == load.operation_type
                        and tuple(
                            sorted(
                                (
                                    rule.family_a.strip(),
                                    rule.family_b.strip(),
                                )
                            )
                        )
                        == pair
                    ]
                    if len(matches) == 1:
                        compatible = matches[0].rule_type == "allow"
                    else:
                        compatible = bool(
                            left_recipe.compatibility_group
                            and left_recipe.compatibility_group
                            == right_recipe.compatibility_group
                        )
                    if not compatible:
                        add(
                            "MLCC-SV027",
                            load_id,
                            f"Members {left.id} and {right.id} are not compatible.",
                        )
            for step in member_steps:
                if batches[step.batch_id].quality_hold:
                    add("MLCC-SV028", step.id, "Quality-held batch was scheduled.")
                trace = load.conversion_evidence.get(step.batch_id)
                if not trace or trace.get("load_quantity") is None:
                    add("MLCC-SV029", step.id, "Load conversion trace is missing.")
            original = frozen.get(load_id)
            if original and (
                not load.frozen
                or load.equipment_id != original.resource_id
                or load.start_minute != original.start_minute
                or load.end_minute != original.end_minute
                or load.recipe_id != original.recipe_id
                or load.furnace_program_key != original.furnace_program_key
                or load.capacity != original.capacity
                or load.loaded_quantity != original.loaded_quantity
                or load.load_unit != original.load_unit
                or member_ids != tuple(sorted(original.member_task_ids))
            ):
                add("MLCC-SV030", load_id, "Frozen furnace load was changed.")

        load_intervals = defaultdict(list)
        for load in loads.values():
            load_intervals[load.equipment_id].append(load)
        for resource_id, values in load_intervals.items():
            ordered = sorted(
                values,
                key=lambda item: (item.start_minute, item.end_minute, item.load_id),
            )
            for previous, current in zip(ordered, ordered[1:]):
                if previous.end_minute > current.start_minute:
                    add(
                        "MLCC-SV031",
                        resource_id,
                        f"Furnace loads {previous.load_id} and {current.load_id} overlap.",
                    )

        for task_id, step in steps.items():
            assignment = assignments.get(task_id)
            if assignment is None:
                continue
            for predecessor_id in step.predecessor_ids:
                predecessor = assignments.get(predecessor_id)
                if predecessor is None:
                    continue
                if (
                    assignment.start_minute
                    < predecessor.end_minute + step.minimum_wait_minutes
                ):
                    add(
                        "MLCC-SV013",
                        task_id,
                        f"Precedence after {predecessor_id} is violated.",
                    )
                if (
                    step.maximum_wait_minutes is not None
                    and assignment.start_minute
                    > predecessor.end_minute + step.maximum_wait_minutes
                ):
                    add(
                        "MLCC-SV014",
                        task_id,
                        f"Maximum wait after {predecessor_id} is violated.",
                    )

        solution_orders = {item.order_id: item for item in solution.orders}
        final_ends = defaultdict(list)
        for batch_id in {step.batch_id for step in steps.values()}:
            batch_steps = [step for step in steps.values() if step.batch_id == batch_id]
            maximum_sequence = max(step.sequence for step in batch_steps)
            final_ends[batch_id] = [
                assignments[step.id].end_minute
                for step in batch_steps
                if step.sequence == maximum_sequence and step.id in assignments
            ]
        for order in instance.customer_orders:
            if not final_ends.get(order.batch_id):
                continue
            result = solution_orders.get(order.id)
            if result is None:
                add("MLCC-SV015", order.id, "Order completion result is missing.")
                continue
            expected_completion = max(final_ends[order.batch_id])
            expected_tardiness = max(
                0,
                expected_completion
                - (
                    instance.window.horizon_minutes
                    if order.due_minute is None
                    else order.due_minute
                ),
            )
            if (
                result.completion_minute != expected_completion
                or result.tardiness_minutes != expected_tardiness
                or result.weighted_tardiness
                != expected_tardiness * result.priority_weight
            ):
                add(
                    "MLCC-SV016",
                    order.id,
                    "Order completion or tardiness is inconsistent.",
                )

        if (
            solution.solution_mode == "phase3c_transition"
            or solution.furnace_transitions
        ):
            rule_snapshot = transition_rule_snapshot(instance)
            if (
                solution.phase3c_metrics.get("transition_rule_resolution_mode")
                != rule_snapshot.resolution_mode
                or solution.phase3c_metrics.get("transition_rule_snapshot_at")
                != rule_snapshot.snapshot_at
                or solution.phase3c_metrics.get(
                    "transition_rule_snapshot_fingerprint"
                )
                != rule_snapshot.fingerprint
                or tuple(
                    solution.phase3c_metrics.get(
                        "effective_transition_rule_ids",
                        (),
                    )
                )
                != rule_snapshot.effective_rule_ids
            ):
                add(
                    "MLCC-SV047",
                    "transition_rule_snapshot",
                    "Solution transition-rule snapshot differs from the planning origin.",
                )
            programs = {item.id: item for item in instance.furnace_programs}
            states = {
                item.resource_id: item for item in instance.furnace_state_snapshots
            }
            rules = {item.id: item for item in instance.furnace_transition_rules}
            transitions_by_successor = defaultdict(list)
            transitions_by_predecessor = defaultdict(list)
            for transition in solution.furnace_transitions:
                transitions_by_successor[transition.successor_load_id].append(
                    transition
                )
                if transition.predecessor_load_id:
                    transitions_by_predecessor[transition.predecessor_load_id].append(
                        transition
                    )

            for load_id, load in sorted(loads.items()):
                member_steps = [
                    steps[item] for item in load.member_task_ids if item in steps
                ]
                member_recipe_ids = tuple(
                    sorted({item.recipe_id for item in member_steps})
                )
                member_program_ids = {
                    recipes[item].furnace_program_id
                    for item in member_recipe_ids
                    if item in recipes
                }
                expected_program_id = (
                    next(iter(member_program_ids))
                    if len(member_program_ids) == 1
                    else None
                )
                expected_recipe_id = (
                    member_recipe_ids[0] if len(member_recipe_ids) == 1 else None
                )
                program = programs.get(load.furnace_program_id)
                if (
                    not member_steps
                    or expected_program_id is None
                    or load.furnace_program_id != expected_program_id
                    or program is None
                    or load.furnace_program_key != program.program_key
                    or load.furnace_program_version != program.version
                    or tuple(sorted(load.member_recipe_ids)) != member_recipe_ids
                    or load.recipe_id != expected_recipe_id
                    or (expected_recipe_id is None and load.recipe_version is not None)
                ):
                    add(
                        "MLCC-SV032",
                        load_id,
                        "Furnace load recipe/program identity is inconsistent.",
                    )

                incoming = transitions_by_successor.get(load_id, ())
                if len(incoming) != 1:
                    add(
                        "MLCC-SV033",
                        load_id,
                        "Furnace load must have exactly one incoming transition.",
                    )
                outgoing = transitions_by_predecessor.get(load_id, ())
                if len(outgoing) > 1:
                    add(
                        "MLCC-SV034",
                        load_id,
                        "Furnace load has more than one successor.",
                    )
                expected_predecessor = (
                    incoming[0].predecessor_load_id if len(incoming) == 1 else None
                )
                expected_successor = (
                    outgoing[0].successor_load_id if len(outgoing) == 1 else None
                )
                if (
                    load.predecessor_load_id != expected_predecessor
                    or load.successor_load_id != expected_successor
                    or (
                        len(incoming) == 1
                        and load.setup_before_minutes != incoming[0].duration_minutes
                    )
                ):
                    add(
                        "MLCC-SV035",
                        load_id,
                        "Furnace load sequence summary differs from transitions.",
                    )

            transition_ids = set()
            frozen_transitions = {
                item.id: item for item in instance.frozen_furnace_transitions
            }
            for transition in solution.furnace_transitions:
                if transition.transition_id in transition_ids:
                    add(
                        "MLCC-SV036",
                        transition.transition_id,
                        "Furnace transition identifier is duplicated.",
                    )
                transition_ids.add(transition.transition_id)
                successor = loads.get(transition.successor_load_id)
                predecessor = (
                    loads.get(transition.predecessor_load_id)
                    if transition.predecessor_load_id
                    else None
                )
                rule = rules.get(transition.rule_id)
                state = states.get(transition.equipment_id)
                target_program = (
                    programs.get(successor.furnace_program_id) if successor else None
                )
                predecessor_program = (
                    programs.get(predecessor.furnace_program_id)
                    if predecessor
                    else None
                )
                from_state = (
                    predecessor_program.resulting_post_state_key
                    if predecessor_program
                    else (state.state_key if state else None)
                )
                ready_minute = (
                    predecessor.end_minute
                    if predecessor
                    else (state.available_minute if state else 0)
                )
                if (
                    successor is None
                    or successor.equipment_id != transition.equipment_id
                    or (
                        predecessor is not None
                        and predecessor.equipment_id != transition.equipment_id
                    )
                    or transition.end_minute < transition.start_minute
                    or transition.duration_minutes
                    != transition.end_minute - transition.start_minute
                    or transition.start_minute < ready_minute
                    or transition.end_minute > successor.start_minute
                    or rule is None
                    or target_program is None
                    or from_state is None
                    or transition.from_state_key != from_state
                    or transition.to_program_key != target_program.program_key
                    or rule.transition_type != transition.transition_type
                    or rule.duration_minutes != transition.duration_minutes
                    or not rule.allowed
                    or not rule.enabled
                    or transition.status != "proposed"
                ):
                    add(
                        "MLCC-SV037",
                        transition.transition_id,
                        "Furnace transition fields, direction, state or duration are invalid.",
                    )
                elif successor:
                    evidence = transition.resolution_evidence
                    if (
                        evidence.get("transition_rule_resolution_mode")
                        != rule_snapshot.resolution_mode
                        or evidence.get("transition_rule_snapshot_at")
                        != rule_snapshot.snapshot_at
                        or evidence.get("transition_rule_snapshot_fingerprint")
                        != rule_snapshot.fingerprint
                    ):
                        add(
                            "MLCC-SV047",
                            transition.transition_id,
                            "Transition evidence uses a different rule snapshot.",
                        )
                    resolution = resolve_transition_rule(
                        instance,
                        transition.equipment_id,
                        successor.operation_type,
                        from_state,
                        successor.furnace_program_id,
                        rule_snapshot,
                    )
                    if (
                        resolution.conflict
                        or not resolution.allowed
                        or resolution.rule.id != transition.rule_id
                        or resolution.scope_level != transition.rule_scope_level
                    ):
                        add(
                            "MLCC-SV038",
                            transition.transition_id,
                            "Furnace transition rule does not resolve uniquely.",
                        )
                resource = equipment.get(transition.equipment_id)
                if resource and not any(
                    start <= transition.start_minute and transition.end_minute <= end
                    for start, end in available_segments(
                        resource, instance.window.horizon_minutes
                    )
                ):
                    add(
                        "MLCC-SV039",
                        transition.transition_id,
                        "Furnace transition overlaps unavailable calendar time.",
                    )

                original = frozen_transitions.get(transition.transition_id)
                if original and (
                    not transition.frozen
                    or transition.equipment_id != original.resource_id
                    or transition.predecessor_load_id != original.predecessor_load_id
                    or transition.successor_load_id != original.successor_load_id
                    or transition.rule_id != original.transition_rule_id
                    or transition.transition_type != original.transition_type
                    or transition.start_minute != original.start_minute
                    or transition.end_minute != original.end_minute
                    or transition.status != original.status
                ):
                    add(
                        "MLCC-SV040",
                        transition.transition_id,
                        "Frozen furnace transition was changed.",
                    )

            for transition_id in sorted(set(frozen_transitions) - transition_ids):
                add(
                    "MLCC-SV041",
                    transition_id,
                    "Frozen furnace transition is missing.",
                )

            for resource_id in sorted({item.equipment_id for item in loads.values()}):
                resource_loads = {
                    item.load_id: item
                    for item in loads.values()
                    if item.equipment_id == resource_id
                }
                initial = [
                    item
                    for item in solution.furnace_transitions
                    if item.equipment_id == resource_id
                    and item.predecessor_load_id is None
                ]
                if resource_loads and len(initial) != 1:
                    add(
                        "MLCC-SV042",
                        resource_id,
                        "Furnace sequence must have exactly one initial-state arc.",
                    )
                visited = set()
                current = initial[0].successor_load_id if len(initial) == 1 else None
                while current:
                    if current in visited:
                        add(
                            "MLCC-SV043",
                            resource_id,
                            "Furnace load sequence contains a cycle.",
                        )
                        break
                    if current not in resource_loads:
                        add(
                            "MLCC-SV044",
                            resource_id,
                            "Furnace sequence crosses equipment.",
                        )
                        break
                    visited.add(current)
                    outgoing = transitions_by_predecessor.get(current, ())
                    current = (
                        outgoing[0].successor_load_id if len(outgoing) == 1 else None
                    )
                if visited != set(resource_loads):
                    add(
                        "MLCC-SV045",
                        resource_id,
                        "Furnace sequence does not cover every load exactly once.",
                    )

                activities = []
                for load in resource_loads.values():
                    activities.append(
                        (
                            load.start_minute,
                            load.end_minute,
                            f"load:{load.load_id}",
                        )
                    )
                for transition in solution.furnace_transitions:
                    if (
                        transition.equipment_id == resource_id
                        and transition.duration_minutes > 0
                    ):
                        activities.append(
                            (
                                transition.start_minute,
                                transition.end_minute,
                                f"transition:{transition.transition_id}",
                            )
                        )
                for assignment in assignments.values():
                    if (
                        assignment.resource_id == resource_id
                        and assignment.stage not in FURNACE_STAGES
                    ):
                        activities.append(
                            (
                                assignment.start_minute,
                                assignment.end_minute,
                                f"task:{assignment.task_id}",
                            )
                        )
                activities.sort()
                for previous, current in zip(activities, activities[1:]):
                    if previous[1] > current[0]:
                        add(
                            "MLCC-SV046",
                            resource_id,
                            f"Furnace activities {previous[2]} and {current[2]} overlap.",
                        )

        unique = {
            (item.code, item.object_id, item.message): item for item in violations
        }
        return SolutionValidationReport(
            tuple(
                sorted(
                    unique.values(),
                    key=lambda item: (item.code, item.object_id, item.message),
                )
            )
        )
