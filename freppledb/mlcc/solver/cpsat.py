"""Pure CP-SAT furnace batching and load optimization for MLCC phase 3B."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from decimal import Decimal
from math import ceil
from time import perf_counter

import ortools
from ortools.sat.python import cp_model

from . import phase3a
from .constraints import (
    FURNACE_STAGES,
    available_segments,
    capability_index,
    eligible_resources,
    load_requirement,
    material_ready_minute,
    schedulable_steps,
)
from .serializer import planning_instance_fingerprint
from .solution import (
    FurnaceLoadAssignment,
    ObjectiveStage,
    OrderSchedule,
    SchedulingSolution,
    SolverParameters,
    TaskAssignment,
)
from .solution_validator import SchedulingSolutionValidator
from .validator import PlanningInstanceValidator

PrecheckBlockedError = phase3a.PrecheckBlockedError
ModelBuildError = phase3a.ModelBuildError
_status_name = phase3a._status_name
MAX_CANDIDATE_MEMBERS_PER_LOAD = 32


@dataclass
class _LoadArtifact:
    load_id: str
    stage: str
    program_key: str
    recipe_id: str
    duration: int
    active: object
    start: object
    end: object
    members: tuple
    resources: tuple
    frozen: bool
    status: str


@dataclass
class _Artifacts:
    model: cp_model.CpModel
    steps: tuple
    starts: dict
    ends: dict
    resource_choices: dict
    loads: tuple
    order_variables: dict
    weighted_tardiness: object
    load_count: object
    makespan: object


def _priority_weights(orders):
    priorities = [max(1, order.priority) for order in orders]
    maximum = max(priorities, default=1)
    return {order.id: max(1, maximum + 1 - max(1, order.priority)) for order in orders}


def _pair_evidence(instance, left, right):
    recipes = {item.id: item for item in instance.recipes}
    batches = {item.id: item for item in instance.batches}
    left_recipe = recipes[left.recipe_id]
    right_recipe = recipes[right.recipe_id]
    left_family = batches[left.batch_id].product_family.strip()
    right_family = batches[right.batch_id].product_family.strip()
    pair = tuple(sorted((left_family, right_family)))
    matches = [
        item
        for item in instance.compatibility_rules
        if item.enabled
        and item.stage == left.stage
        and tuple(sorted((item.family_a.strip(), item.family_b.strip()))) == pair
    ]
    if len(matches) == 1:
        if matches[0].rule_type == "forbid":
            return None
        return f"pair_rule:{matches[0].id}"
    if (
        left_recipe.compatibility_group
        and left_recipe.compatibility_group == right_recipe.compatibility_group
    ):
        return f"certified_group:{left_recipe.compatibility_group}"
    return None


def _compatibility_classes(instance, steps):
    recipes = {item.id: item for item in instance.recipes}
    batches = {item.id: item for item in instance.batches}
    result = defaultdict(list)
    for step in steps:
        recipe = recipes[step.recipe_id]
        batch = batches[step.batch_id]
        key = (
            batch.product_family.strip(),
            recipe.compatibility_group or "",
        )
        result[key].append(step)
    return {
        key: tuple(sorted(value, key=lambda item: item.id))
        for key, value in sorted(result.items())
    }


def _candidate_slot_memberships(steps, slot_count):
    """Keep each task in a small, stable neighborhood of candidate loads."""

    preferred = {
        step.id: min(slot_count - 1, index * slot_count // len(steps))
        for index, step in enumerate(steps)
    }
    if len(steps) <= MAX_CANDIDATE_MEMBERS_PER_LOAD * 2:
        return (steps,) * slot_count, preferred
    return (
        tuple(
            tuple(step for step in steps if abs(preferred[step.id] - slot_number) <= 1)
            for slot_number in range(slot_count)
        ),
        preferred,
    )


def _build_model(instance, baseline_weighted_tardiness):
    horizon = instance.window.horizon_minutes
    steps = schedulable_steps(instance)
    if horizon <= 0 or not steps:
        raise ModelBuildError("Planning horizon and schedulable tasks are required")
    phase3a._validate_identity(instance, steps)

    model = cp_model.CpModel()
    starts = {}
    ends = {}
    resource_choices = defaultdict(list)
    intervals_by_resource = defaultdict(list)
    equipment = {item.id: item for item in instance.equipment}
    recipes = {item.id: item for item in instance.recipes}
    due_by_batch = {
        item.id: (horizon if item.due_minute is None else item.due_minute)
        for item in instance.batches
    }
    capabilities = capability_index(instance)
    steps_by_id = {item.id: item for item in steps}

    for step in steps:
        start = model.NewIntVar(0, horizon, f"start:{step.id}")
        end = model.NewIntVar(0, horizon, f"end:{step.id}")
        starts[step.id] = start
        ends[step.id] = end
        model.Add(end == start + step.duration_minutes)
        model.Add(start >= material_ready_minute(instance, step))

    frozen_member_ids = {
        task_id
        for load in instance.frozen_furnace_loads
        for task_id in load.member_task_ids
    }
    normal_steps = tuple(item for item in steps if item.stage not in FURNACE_STAGES)
    for step in normal_steps:
        fixed = step.frozen or step.started
        if fixed:
            if (
                not step.assigned_resource_id
                or step.original_start_minute is None
                or step.original_end_minute is None
            ):
                raise ModelBuildError(
                    f"Frozen task {step.id} requires resource, start and end"
                )
            model.Add(starts[step.id] == step.original_start_minute)
            model.Add(ends[step.id] == step.original_end_minute)
        resources = eligible_resources(instance, step, capabilities)
        if fixed:
            resources = (step.assigned_resource_id,)
        choices = []
        for resource_id in resources:
            for segment_number, (segment_start, segment_end) in enumerate(
                available_segments(equipment[resource_id], horizon), 1
            ):
                if segment_start + step.duration_minutes > segment_end:
                    continue
                presence = model.NewBoolVar(
                    f"assign:{step.id}:{resource_id}:{segment_number}"
                )
                interval = model.NewOptionalIntervalVar(
                    starts[step.id],
                    step.duration_minutes,
                    ends[step.id],
                    presence,
                    f"interval:{step.id}:{resource_id}:{segment_number}",
                )
                model.Add(starts[step.id] >= segment_start).OnlyEnforceIf(presence)
                model.Add(ends[step.id] <= segment_end).OnlyEnforceIf(presence)
                choices.append((presence, resource_id))
                intervals_by_resource[resource_id].append(interval)
        resource_choices[step.id].extend(choices)
        if choices:
            model.Add(sum(item[0] for item in choices) == 1)
            for index, (presence, _) in enumerate(choices):
                model.AddHint(presence, int(index == 0))
        else:
            model.AddBoolOr([])

    loads = []
    for frozen in instance.frozen_furnace_loads:
        members = tuple(
            steps_by_id[item] for item in frozen.member_task_ids if item in steps_by_id
        )
        if not members:
            raise ModelBuildError(f"Frozen load {frozen.id} has no members")
        active = model.NewConstant(1)
        start = model.NewIntVar(
            frozen.start_minute, frozen.start_minute, f"load-start:{frozen.id}"
        )
        end = model.NewIntVar(
            frozen.end_minute, frozen.end_minute, f"load-end:{frozen.id}"
        )
        resource_presence = model.NewConstant(1)
        interval = model.NewIntervalVar(
            start,
            frozen.end_minute - frozen.start_minute,
            end,
            f"load-interval:{frozen.id}",
        )
        intervals_by_resource[frozen.resource_id].append(interval)
        member_values = []
        for step in members:
            presence = model.NewConstant(1)
            member_values.append((presence, step.id))
            model.Add(starts[step.id] == start)
            model.Add(ends[step.id] == end)
            resource_choices[step.id].append((resource_presence, frozen.resource_id))
        loads.append(
            _LoadArtifact(
                frozen.id,
                frozen.stage,
                frozen.furnace_program_key,
                frozen.recipe_id,
                frozen.end_minute - frozen.start_minute,
                active,
                start,
                end,
                tuple(member_values),
                ((resource_presence, frozen.resource_id),),
                True,
                frozen.status,
            )
        )

    furnace_steps = tuple(
        item
        for item in steps
        if item.stage in FURNACE_STAGES and item.id not in frozen_member_ids
    )
    grouped = defaultdict(list)
    for step in furnace_steps:
        recipe = recipes[step.recipe_id]
        grouped[(step.stage, recipe.furnace_program_key, step.duration_minutes)].append(
            step
        )

    for group_number, (group_key, group_steps_value) in enumerate(
        sorted(grouped.items()), 1
    ):
        stage, program_key, duration = group_key
        group_steps = tuple(
            sorted(
                group_steps_value,
                key=lambda item: (
                    (
                        horizon
                        if item.original_start_minute is None
                        else item.original_start_minute
                    ),
                    due_by_batch[item.batch_id],
                    item.id,
                ),
            )
        )
        classes = _compatibility_classes(instance, group_steps)
        representatives = {key: value[0] for key, value in classes.items()}
        eligible = {
            step.id: eligible_resources(instance, step, capabilities)
            for step in group_steps
        }
        resource_ids = tuple(
            sorted({item for values in eligible.values() for item in values})
        )
        canonical_recipe = min(step.recipe_id for step in group_steps)
        class_keys = sorted(classes)
        mixing_possible = any(
            len(values) > 1
            and _pair_evidence(instance, values[0], values[0]) is not None
            for values in classes.values()
        ) or any(
            _pair_evidence(
                instance,
                representatives[left],
                representatives[right],
            )
            is not None
            for index, left in enumerate(class_keys)
            for right in class_keys[index + 1 :]
        )
        if mixing_possible:
            minimum_quantities = [
                min(
                    load_requirement(step, resource_id).quantity
                    for resource_id in eligible[step.id]
                )
                for step in group_steps
            ]
            maximum_capacity = max(
                int(equipment[resource_id].capacity) for resource_id in resource_ids
            )
            slot_count = min(
                len(group_steps),
                max(
                    1,
                    ceil(sum(minimum_quantities) / maximum_capacity),
                    ceil(len(group_steps) / MAX_CANDIDATE_MEMBERS_PER_LOAD),
                    min(4, len(group_steps)),
                ),
            )
            slot_memberships, preferred_slot_by_task = _candidate_slot_memberships(
                group_steps, slot_count
            )
        else:
            # Default-deny compatibility produces deterministic singleton loads
            # without creating a batch-by-batch assignment matrix.
            slot_memberships = tuple((step,) for step in group_steps)
            preferred_slot_by_task = {
                step.id: index for index, step in enumerate(group_steps)
            }
        previous_active = None
        for slot, slot_steps in enumerate(slot_memberships, 1):
            preferred_task_ids = {
                task_id
                for task_id, preferred_slot in preferred_slot_by_task.items()
                if preferred_slot == slot - 1
            }
            load_id = f"furnace_load:{stage}:{program_key}:{slot:04d}"
            active = model.NewBoolVar(f"load-active:{group_number}:{slot}")
            start = model.NewIntVar(0, horizon, f"load-start:{group_number}:{slot}")
            end = model.NewIntVar(0, horizon, f"load-end:{group_number}:{slot}")
            model.Add(end == start + duration)
            members = tuple(
                (
                    model.NewBoolVar(f"load-member:{group_number}:{slot}:{step.id}"),
                    step.id,
                )
                for step in slot_steps
            )
            model.AddHint(active, int(bool(preferred_task_ids)))
            for member, task_id in members:
                model.AddHint(member, int(task_id in preferred_task_ids))
            model.Add(sum(value for value, _ in members) >= active)
            model.Add(sum(value for value, _ in members) <= len(members) * active)
            if previous_active is not None:
                model.Add(previous_active >= active)
            previous_active = active

            resource_values = []
            for resource_id in resource_ids:
                resource_presence = model.NewBoolVar(
                    f"load-resource:{group_number}:{slot}:{resource_id}"
                )
                segment_values = []
                for segment_number, (segment_start, segment_end) in enumerate(
                    available_segments(equipment[resource_id], horizon), 1
                ):
                    if segment_start + duration > segment_end:
                        continue
                    segment_presence = model.NewBoolVar(
                        f"load-segment:{group_number}:{slot}:{resource_id}:{segment_number}"
                    )
                    interval = model.NewOptionalIntervalVar(
                        start,
                        duration,
                        end,
                        segment_presence,
                        f"load-interval:{group_number}:{slot}:{resource_id}:{segment_number}",
                    )
                    model.Add(start >= segment_start).OnlyEnforceIf(segment_presence)
                    model.Add(end <= segment_end).OnlyEnforceIf(segment_presence)
                    intervals_by_resource[resource_id].append(interval)
                    segment_values.append(segment_presence)
                if segment_values:
                    model.Add(sum(segment_values) == resource_presence)
                else:
                    model.Add(resource_presence == 0)
                resource_values.append((resource_presence, resource_id))
            model.Add(sum(value for value, _ in resource_values) == active)
            hinted_resource = next(
                (
                    resource_id
                    for resource_id in resource_ids
                    if preferred_task_ids
                    and all(
                        resource_id in eligible[task_id]
                        for task_id in preferred_task_ids
                    )
                    and sum(
                        load_requirement(steps_by_id[task_id], resource_id).quantity
                        for task_id in preferred_task_ids
                    )
                    <= int(equipment[resource_id].capacity)
                ),
                None,
            )
            for resource_presence, resource_id in resource_values:
                model.AddHint(
                    resource_presence,
                    int(resource_id == hinted_resource),
                )

            member_map = dict((task_id, value) for value, task_id in members)
            for step in slot_steps:
                member = member_map[step.id]
                model.Add(starts[step.id] == start).OnlyEnforceIf(member)
                model.Add(ends[step.id] == end).OnlyEnforceIf(member)
                for resource_presence, resource_id in resource_values:
                    if resource_id not in eligible[step.id]:
                        model.Add(member + resource_presence <= 1)
                        continue
                    combined = model.NewBoolVar(
                        f"task-resource:{step.id}:{group_number}:{slot}:{resource_id}"
                    )
                    model.Add(combined <= member)
                    model.Add(combined <= resource_presence)
                    model.Add(combined >= member + resource_presence - 1)
                    resource_choices[step.id].append((combined, resource_id))

            slot_classes = _compatibility_classes(instance, slot_steps)
            slot_representatives = {
                key: value[0] for key, value in slot_classes.items()
            }
            class_presence = {}
            for class_key, class_steps in slot_classes.items():
                present = model.NewBoolVar(
                    f"load-class:{group_number}:{slot}:{class_key[0]}:{class_key[1]}"
                )
                values = [member_map[item.id] for item in class_steps]
                for value in values:
                    model.Add(value <= present)
                model.Add(present <= sum(values))
                class_presence[class_key] = present
                if (
                    _pair_evidence(
                        instance,
                        representatives[class_key],
                        representatives[class_key],
                    )
                    is None
                ):
                    model.Add(sum(values) <= 1)
            slot_class_keys = sorted(slot_classes)
            for index, left in enumerate(slot_class_keys):
                for right in slot_class_keys[index + 1 :]:
                    if (
                        _pair_evidence(
                            instance,
                            slot_representatives[left],
                            slot_representatives[right],
                        )
                        is None
                    ):
                        model.Add(class_presence[left] + class_presence[right] <= 1)

            for resource_presence, resource_id in resource_values:
                quantities = [
                    (
                        member_map[step.id],
                        load_requirement(step, resource_id).quantity,
                    )
                    for step in slot_steps
                    if load_requirement(step, resource_id) is not None
                    and load_requirement(step, resource_id).quantity is not None
                ]
                total = sum(value * quantity for value, quantity in quantities)
                maximum = sum(quantity for _, quantity in quantities)
                capacity = int(equipment[resource_id].capacity)
                model.Add(total <= capacity + maximum * (1 - resource_presence))

            loads.append(
                _LoadArtifact(
                    load_id,
                    stage,
                    program_key,
                    canonical_recipe,
                    duration,
                    active,
                    start,
                    end,
                    members,
                    tuple(resource_values),
                    False,
                    "proposed",
                )
            )

    for step in furnace_steps:
        memberships = [
            value
            for load in loads
            if not load.frozen
            for value, task_id in load.members
            if task_id == step.id
        ]
        if memberships:
            model.Add(sum(memberships) == 1)
        else:
            model.AddBoolOr([])
        if resource_choices[step.id]:
            model.Add(sum(value for value, _ in resource_choices[step.id]) == 1)

    for intervals in intervals_by_resource.values():
        model.AddNoOverlap(intervals)

    step_ids = set(starts)
    for step in steps:
        for predecessor_id in step.predecessor_ids:
            if predecessor_id not in step_ids:
                raise ModelBuildError(
                    f"Task {step.id} references unknown predecessor {predecessor_id}"
                )
            model.Add(
                starts[step.id] >= ends[predecessor_id] + step.minimum_wait_minutes
            )
            if step.maximum_wait_minutes is not None:
                model.Add(
                    starts[step.id] <= ends[predecessor_id] + step.maximum_wait_minutes
                )

    final_end_by_batch = defaultdict(list)
    by_batch = defaultdict(list)
    for step in steps:
        by_batch[step.batch_id].append(step)
    for batch_id, batch_steps in by_batch.items():
        maximum_sequence = max(item.sequence for item in batch_steps)
        final_end_by_batch[batch_id] = [
            ends[item.id] for item in batch_steps if item.sequence == maximum_sequence
        ]

    weights = _priority_weights(instance.customer_orders)
    order_variables = {}
    weighted_terms = []
    for order in instance.customer_orders:
        batch_ends = final_end_by_batch.get(order.batch_id, ())
        if not batch_ends:
            continue
        completion = model.NewIntVar(0, horizon, f"completion:{order.id}")
        model.AddMaxEquality(completion, batch_ends)
        due = horizon if order.due_minute is None else order.due_minute
        tardiness = model.NewIntVar(0, max(0, horizon - due), f"tardiness:{order.id}")
        model.AddMaxEquality(tardiness, [completion - due, 0])
        weight = weights[order.id]
        weighted_terms.append(tardiness * weight)
        order_variables[order.id] = (completion, tardiness, weight)
    weighted_tardiness = sum(weighted_terms) if weighted_terms else 0
    model.Add(weighted_tardiness <= baseline_weighted_tardiness)
    load_count = sum(load.active for load in loads)
    makespan = model.NewIntVar(0, horizon, "makespan")
    model.AddMaxEquality(makespan, list(ends.values()))
    return _Artifacts(
        model,
        steps,
        starts,
        ends,
        dict(resource_choices),
        tuple(loads),
        order_variables,
        weighted_tardiness,
        load_count,
        makespan,
    )


def _configure_solver(parameters, time_limit):
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(0.001, float(time_limit))
    solver.parameters.num_search_workers = parameters.num_search_workers
    solver.parameters.random_seed = parameters.random_seed
    solver.parameters.log_search_progress = parameters.log_search_progress
    return solver


def _stage_result(name, solver, status, value):
    bound = (
        float(solver.BestObjectiveBound())
        if name != "feasibility" and status in (cp_model.FEASIBLE, cp_model.OPTIMAL)
        else None
    )
    return ObjectiveStage(
        name,
        _status_name(status),
        value,
        bound,
        round(solver.WallTime(), 6),
    )


def _conversion_trace(step, resource_id):
    requirement = load_requirement(step, resource_id)
    return {
        "source_quantity": requirement.source_quantity,
        "source_unit": requirement.source_unit,
        "load_quantity": requirement.quantity,
        "load_unit": requirement.load_unit,
        "conversion_id": requirement.conversion_id,
        "numerator": requirement.conversion_numerator,
        "denominator": requirement.conversion_denominator,
    }


def _snapshot(instance, artifacts, solver):
    steps = {item.id: item for item in artifacts.steps}
    recipes = {item.id: item for item in instance.recipes}
    programs = {item.id: item for item in instance.furnace_programs}
    batches = {item.id: item for item in instance.batches}
    task_load = {}
    furnace_loads = []
    for load in sorted(artifacts.loads, key=lambda item: item.load_id):
        if not solver.BooleanValue(load.active):
            continue
        resource_id = next(
            resource_id
            for presence, resource_id in load.resources
            if solver.BooleanValue(presence)
        )
        member_task_ids = tuple(
            sorted(
                task_id
                for presence, task_id in load.members
                if solver.BooleanValue(presence)
            )
        )
        for task_id in member_task_ids:
            task_load[task_id] = load.load_id
        member_batch_ids = tuple(
            sorted({steps[item].batch_id for item in member_task_ids})
        )
        requirements = [
            load_requirement(steps[item], resource_id) for item in member_task_ids
        ]
        loaded = sum(item.quantity for item in requirements)
        capacity = int(
            next(item.capacity for item in instance.equipment if item.id == resource_id)
        )
        evidence = {}
        for task_id in member_task_ids:
            values = []
            for other_id in member_task_ids:
                if other_id == task_id:
                    continue
                pair = _pair_evidence(instance, steps[task_id], steps[other_id])
                values.append(f"{batches[steps[other_id].batch_id].id}:{pair}")
            evidence[steps[task_id].batch_id] = tuple(sorted(values))
        member_recipe_ids = tuple(
            sorted({steps[item].recipe_id for item in member_task_ids})
        )
        recipe_id = member_recipe_ids[0] if len(member_recipe_ids) == 1 else None
        recipe = recipes[recipe_id] if recipe_id else None
        member_program_ids = {
            recipes[item].furnace_program_id for item in member_recipe_ids
        }
        program_id = (
            next(iter(member_program_ids)) if len(member_program_ids) == 1 else None
        )
        program = programs.get(program_id)
        furnace_loads.append(
            FurnaceLoadAssignment(
                load_id=load.load_id,
                operation_type=load.stage,
                equipment_id=resource_id,
                recipe_id=recipe_id,
                recipe_version=recipe.version if recipe else None,
                furnace_program_key=load.program_key,
                start_minute=solver.Value(load.start),
                end_minute=solver.Value(load.end),
                capacity=capacity,
                loaded_quantity=loaded,
                load_unit=requirements[0].load_unit,
                utilization=Decimal(loaded) / Decimal(capacity),
                member_batch_ids=member_batch_ids,
                member_task_ids=member_task_ids,
                compatibility_evidence=evidence,
                conversion_evidence={
                    steps[item].batch_id: _conversion_trace(steps[item], resource_id)
                    for item in member_task_ids
                },
                frozen=load.frozen,
                status=load.status,
                constraint_summary={
                    "pairwise_compatible": True,
                    "capacity_feasible": loaded <= capacity,
                    "synchronized": True,
                },
                furnace_program_id=program_id,
                furnace_program_version=program.version if program else None,
                member_recipe_ids=member_recipe_ids,
            )
        )
    assignments = []
    for task_id in sorted(artifacts.starts):
        resource_id = next(
            resource_id
            for presence, resource_id in artifacts.resource_choices[task_id]
            if solver.BooleanValue(presence)
        )
        step = steps[task_id]
        assignments.append(
            TaskAssignment(
                task_id,
                step.batch_id,
                step.stage,
                resource_id,
                solver.Value(artifacts.starts[task_id]),
                solver.Value(artifacts.ends[task_id]),
                step.frozen or step.started,
                task_load.get(task_id),
            )
        )
    orders_by_id = {item.id: item for item in instance.customer_orders}
    orders = []
    for order_id in sorted(artifacts.order_variables):
        completion, tardiness, weight = artifacts.order_variables[order_id]
        order = orders_by_id[order_id]
        value = solver.Value(tardiness)
        orders.append(
            OrderSchedule(
                order_id,
                solver.Value(completion),
                order.due_minute,
                value,
                order.priority,
                weight,
                value * weight,
            )
        )
    return tuple(assignments), tuple(furnace_loads), tuple(orders)


def _utilization_metrics(loads):
    values = sorted(
        int(item.loaded_quantity * 1_000_000 // item.capacity) for item in loads
    )
    if not values:
        return {"average_ppm": 0, "p50_ppm": 0, "p90_ppm": 0}
    percentile = lambda numerator: values[
        min(len(values) - 1, ((len(values) - 1) * numerator + 99) // 100)
    ]
    return {
        "average_ppm": sum(values) // len(values),
        "p50_ppm": percentile(50),
        "p90_ppm": percentile(90),
    }


def _metrics(solution):
    weighted = sum(item.weighted_tardiness for item in solution.orders)
    makespan = max((item.end_minute for item in solution.assignments), default=0)
    return {
        "weighted_tardiness": weighted,
        "furnace_load_count": len(solution.furnace_loads),
        "makespan": makespan,
        "utilization": _utilization_metrics(solution.furnace_loads),
    }


def _baseline_with_loads(instance, solution, parameters):
    recipes = {item.id: item for item in instance.recipes}
    programs = {item.id: item for item in instance.furnace_programs}
    steps = {item.id: item for item in instance.steps}
    loads = []
    assignments = []
    frozen_by_task = {
        task_id: load
        for load in instance.frozen_furnace_loads
        for task_id in load.member_task_ids
    }
    for assignment in solution.assignments:
        if assignment.stage not in FURNACE_STAGES:
            assignments.append(assignment)
            continue
        step = steps[assignment.task_id]
        if assignment.task_id in frozen_by_task:
            assignments.append(
                replace(
                    assignment,
                    furnace_load_id=frozen_by_task[assignment.task_id].id,
                )
            )
            continue
        requirement = load_requirement(step, assignment.resource_id)
        resource = next(
            item for item in instance.equipment if item.id == assignment.resource_id
        )
        recipe = recipes[step.recipe_id]
        program = programs.get(recipe.furnace_program_id)
        load_id = f"phase3a:{assignment.task_id}"
        assignments.append(replace(assignment, furnace_load_id=load_id))
        loads.append(
            FurnaceLoadAssignment(
                load_id,
                assignment.stage,
                assignment.resource_id,
                recipe.id,
                recipe.version,
                recipe.furnace_program_key,
                assignment.start_minute,
                assignment.end_minute,
                int(resource.capacity),
                requirement.quantity,
                requirement.load_unit,
                Decimal(requirement.quantity) / Decimal(resource.capacity),
                (assignment.batch_id,),
                (assignment.task_id,),
                {assignment.batch_id: ()},
                {assignment.batch_id: _conversion_trace(step, assignment.resource_id)},
                assignment.frozen,
                furnace_program_id=recipe.furnace_program_id,
                furnace_program_version=program.version if program else None,
                member_recipe_ids=(recipe.id,),
            )
        )
    for frozen in instance.frozen_furnace_loads:
        member_steps = [steps[item] for item in frozen.member_task_ids]
        recipe = recipes[frozen.recipe_id]
        program = programs.get(frozen.furnace_program_id or recipe.furnace_program_id)
        evidence = {}
        for step in member_steps:
            evidence[step.batch_id] = tuple(
                sorted(
                    f"{steps[other].batch_id}:{_pair_evidence(instance, step, steps[other])}"
                    for other in frozen.member_task_ids
                    if other != step.id
                )
            )
        loads.append(
            FurnaceLoadAssignment(
                frozen.id,
                frozen.stage,
                frozen.resource_id,
                frozen.recipe_id,
                recipe.version,
                frozen.furnace_program_key,
                frozen.start_minute,
                frozen.end_minute,
                frozen.capacity,
                frozen.loaded_quantity,
                frozen.load_unit,
                Decimal(frozen.loaded_quantity) / Decimal(frozen.capacity),
                tuple(sorted(step.batch_id for step in member_steps)),
                tuple(sorted(frozen.member_task_ids)),
                evidence,
                {
                    step.batch_id: _conversion_trace(step, frozen.resource_id)
                    for step in member_steps
                },
                True,
                frozen.status,
                furnace_program_id=(
                    frozen.furnace_program_id or recipe.furnace_program_id
                ),
                furnace_program_version=program.version if program else None,
                member_recipe_ids=(recipe.id,),
            )
        )
    baseline = replace(
        solution,
        parameters=replace(parameters, furnace_mode="one_batch_per_run"),
        assignments=tuple(assignments),
        furnace_loads=tuple(sorted(loads, key=lambda item: item.load_id)),
        solution_mode="phase3a_fallback",
        fallback_reason=None,
    )
    metrics = _metrics(baseline)
    return replace(
        baseline,
        phase3a_baseline_metrics=metrics,
        phase3b_metrics=metrics,
        metric_deltas={
            "weighted_tardiness": 0,
            "furnace_load_count": 0,
            "makespan": 0,
            "utilization_ppm": {
                "average_ppm": 0,
                "p50_ppm": 0,
                "p90_ppm": 0,
            },
        },
        message="Phase-3A one-batch-per-furnace validated fallback.",
    )


def _model_invalid_solution(
    instance,
    parameters,
    started,
    message,
    baseline_metrics=None,
    last_successful_stage=None,
):
    return SchedulingSolution(
        status="MODEL_INVALID",
        input_fingerprint=planning_instance_fingerprint(instance),
        solver_name="Google OR-Tools CP-SAT",
        solver_version=ortools.__version__,
        parameters=replace(parameters, furnace_mode="multi_batch_loads"),
        wall_time_seconds=round(perf_counter() - started, 6),
        message=message,
        solution_mode="phase3b_multi_batch",
        fallback_reason=None,
        last_successful_stage=last_successful_stage,
        phase3a_baseline_metrics=baseline_metrics or {},
    )


def _finalize(instance, parameters, snapshot, stages, started, baseline_metrics):
    assignments, loads, orders = snapshot
    stage_gaps = [
        abs(item.value - item.best_bound) / max(1, abs(item.value))
        for item in stages
        if item.value is not None and item.best_bound is not None
    ]
    optimality_gap = max(stage_gaps) if stage_gaps else None
    solution = SchedulingSolution(
        status=(
            "OPTIMAL"
            if stages and all(item.status == "OPTIMAL" for item in stages)
            else "FEASIBLE"
        ),
        input_fingerprint=planning_instance_fingerprint(instance),
        solver_name="Google OR-Tools CP-SAT",
        solver_version=ortools.__version__,
        parameters=parameters,
        assignments=assignments,
        furnace_loads=loads,
        orders=orders,
        objective_stages=tuple(stages),
        objective_values={
            "weighted_tardiness": sum(item.weighted_tardiness for item in orders),
            "furnace_load_count": len(loads),
            "makespan": max((item.end_minute for item in assignments), default=0),
        },
        wall_time_seconds=round(perf_counter() - started, 6),
        optimality_gap=optimality_gap,
        solution_mode="phase3b_multi_batch",
        fallback_reason=None,
        last_successful_stage=next(
            (
                item.name
                for item in reversed(stages)
                if item.status in ("FEASIBLE", "OPTIMAL")
            ),
            None,
        ),
    )
    metrics = _metrics(solution)
    return replace(
        solution,
        phase3a_baseline_metrics=baseline_metrics,
        phase3b_metrics=metrics,
        metric_deltas={
            "weighted_tardiness": (
                metrics["weighted_tardiness"] - baseline_metrics["weighted_tardiness"]
            ),
            "furnace_load_count": (
                metrics["furnace_load_count"] - baseline_metrics["furnace_load_count"]
            ),
            "makespan": metrics["makespan"] - baseline_metrics["makespan"],
            "utilization_ppm": {
                key: (
                    metrics["utilization"][key] - baseline_metrics["utilization"][key]
                )
                for key in ("average_ppm", "p50_ppm", "p90_ppm")
            },
        },
    )


def solve(instance, parameters=None):
    """Solve phase 3B without accessing Django model instances."""

    parameters = replace(
        parameters or SolverParameters(),
        furnace_mode="multi_batch_loads",
    )
    report = PlanningInstanceValidator().validate(instance)
    if report.blocker_count:
        raise PrecheckBlockedError(report)
    if parameters.max_time_seconds <= 0 or parameters.num_search_workers <= 0:
        raise ValueError("Solver time and worker count must be greater than zero")

    started = perf_counter()
    baseline_parameters = replace(
        parameters,
        max_time_seconds=min(
            max(1.0, parameters.max_time_seconds * 0.25),
            60.0,
        ),
        furnace_mode="one_batch_per_run",
    )
    baseline_raw = phase3a.solve(instance, baseline_parameters)
    if baseline_raw.status not in ("FEASIBLE", "OPTIMAL"):
        return replace(
            baseline_raw,
            solution_mode="phase3a_fallback",
            fallback_reason=f"phase3a_baseline_{baseline_raw.status.lower()}",
        )
    fallback = _baseline_with_loads(instance, baseline_raw, parameters)
    baseline_metrics = fallback.phase3a_baseline_metrics
    fallback_validation = SchedulingSolutionValidator().validate(instance, fallback)
    if not fallback_validation.valid:
        return _model_invalid_solution(
            instance,
            parameters,
            started,
            "Phase-3A fallback failed independent validation: "
            + "; ".join(
                f"{item.code}:{item.object_id}"
                for item in fallback_validation.violations
            ),
            baseline_metrics,
            baseline_raw.last_successful_stage,
        )

    def safe_fallback(reason, last_successful_stage=None):
        return replace(
            fallback,
            fallback_reason=reason,
            last_successful_stage=(
                last_successful_stage or baseline_raw.last_successful_stage
            ),
            message=(
                "Phase-3A one-batch-per-furnace validated fallback. "
                f"Reason: {reason}."
            ),
        )

    remaining = parameters.max_time_seconds - (perf_counter() - started)
    if remaining <= 0.01:
        return safe_fallback("phase3b_time_limit_exhausted_before_model")
    try:
        artifacts = _build_model(
            instance,
            baseline_metrics["weighted_tardiness"],
        )
    except ModelBuildError as exc:
        return _model_invalid_solution(
            instance,
            parameters,
            started,
            str(exc),
            baseline_metrics,
            baseline_raw.last_successful_stage,
        )

    stages = []
    snapshots = []
    objectives = (
        ("feasibility", None, 0.18),
        ("weighted_tardiness", artifacts.weighted_tardiness, 0.38),
        ("furnace_load_count", artifacts.load_count, 0.28),
        ("makespan", artifacts.makespan, 1.0),
    )
    for name, objective, fraction in objectives:
        remaining = parameters.max_time_seconds - (perf_counter() - started)
        if remaining <= 0.01:
            break
        if objective is not None:
            artifacts.model.Minimize(objective)
        limit = remaining if fraction == 1.0 else max(0.01, remaining * fraction)
        solver = _configure_solver(parameters, limit)
        status = solver.Solve(artifacts.model)
        if status not in (cp_model.FEASIBLE, cp_model.OPTIMAL):
            stages.append(_stage_result(name, solver, status, None))
            break
        value = None if objective is None else int(solver.Value(objective))
        stages.append(_stage_result(name, solver, status, value))
        snapshots.append(_snapshot(instance, artifacts, solver))
        if objective is not None:
            artifacts.model.Add(objective <= value)

    if stages and stages[-1].status == "MODEL_INVALID":
        return _model_invalid_solution(
            instance,
            parameters,
            started,
            "CP-SAT rejected the phase-3B model.",
            baseline_metrics,
            (
                next(
                    (
                        item.name
                        for item in reversed(stages[:-1])
                        if item.status in ("FEASIBLE", "OPTIMAL")
                    ),
                    None,
                )
                or baseline_raw.last_successful_stage
            ),
        )
    if not snapshots:
        return safe_fallback(
            (
                "phase3b_unknown"
                if stages and stages[-1].status == "UNKNOWN"
                else "phase3b_no_better_multi_batch_solution"
            )
        )
    candidate = _finalize(
        instance,
        parameters,
        snapshots[-1],
        stages,
        started,
        baseline_metrics,
    )
    candidate_metrics = candidate.phase3b_metrics
    candidate_validation = SchedulingSolutionValidator().validate(instance, candidate)
    if not candidate_validation.valid:
        return _model_invalid_solution(
            instance,
            parameters,
            started,
            "Phase-3B candidate failed independent validation: "
            + "; ".join(
                f"{item.code}:{item.object_id}"
                for item in candidate_validation.violations
            ),
            baseline_metrics,
            candidate.last_successful_stage,
        )
    if (
        candidate_metrics["weighted_tardiness"] > baseline_metrics["weighted_tardiness"]
        or candidate_metrics["furnace_load_count"]
        > baseline_metrics["furnace_load_count"]
    ):
        return safe_fallback(
            "phase3b_no_better_multi_batch_solution",
            candidate.last_successful_stage,
        )
    return candidate
