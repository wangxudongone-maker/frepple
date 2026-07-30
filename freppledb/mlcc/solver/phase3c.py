"""Pure CP-SAT sequence-dependent furnace transitions for MLCC phase 3C.

The module consumes only :class:`PlanningInstance`. Django models are deliberately
kept outside this boundary.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from decimal import Decimal
import hashlib
from time import perf_counter

import ortools
from ortools.sat.python import cp_model

from . import cpsat, phase3a
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
    FurnaceTransitionAssignment,
    ObjectiveStage,
    OrderSchedule,
    SchedulingSolution,
    SolverParameters,
    TaskAssignment,
)
from .solution_validator import SchedulingSolutionValidator
from .transition_rules import resolve_transition_rule, transition_rule_snapshot
from .validator import PlanningInstanceValidator

PrecheckBlockedError = phase3a.PrecheckBlockedError
ModelBuildError = phase3a.ModelBuildError
_status_name = phase3a._status_name
MAX_PREAGGREGATED_MEMBERS_PER_LOAD = 32


@dataclass
class _LoadNode:
    load_id: str
    base: FurnaceLoadAssignment
    stage: str
    duration: int
    member_task_ids: tuple[str, ...]
    furnace_program_id: str
    start: object
    end: object
    resources: tuple[tuple[object, str], ...]
    frozen: bool


@dataclass
class _TransitionArc:
    presence: object
    resource_id: str
    predecessor_load_id: str | None
    successor_load_id: str
    initial_state_id: str | None
    from_state_key: str
    rule: object
    start: object
    end: object
    frozen: bool
    transition_id: str


@dataclass
class _Artifacts:
    model: cp_model.CpModel
    steps: tuple
    starts: dict
    ends: dict
    resource_choices: dict
    loads: tuple[_LoadNode, ...]
    transition_arcs: tuple[_TransitionArc, ...]
    order_variables: dict
    weighted_tardiness: object
    transition_minutes: object
    makespan: object
    transition_rule_snapshot: object


def _candidate_resources(instance, members, duration, indexed_capabilities):
    equipment = {item.id: item for item in instance.equipment}
    candidates = None
    for step in members:
        values = set(eligible_resources(instance, step, indexed_capabilities))
        candidates = values if candidates is None else candidates & values
    result = []
    for resource_id in sorted(candidates or ()):
        resource = equipment.get(resource_id)
        if (
            resource is None
            or resource.capacity is None
            or resource.capacity != resource.capacity.to_integral_value()
            or int(resource.capacity) <= 0
        ):
            continue
        requirements = [load_requirement(step, resource_id) for step in members]
        if any(
            item is None
            or item.quantity is None
            or item.quantity <= 0
            or item.load_unit != resource.load_unit
            for item in requirements
        ):
            continue
        if sum(item.quantity for item in requirements) > int(resource.capacity):
            continue
        if not any(
            segment_end - segment_start >= duration
            for segment_start, segment_end in available_segments(
                resource, instance.window.horizon_minutes
            )
        ):
            continue
        result.append(resource_id)
    return tuple(result)


def _preaggregate_reference(instance, reference):
    """Create a small, deterministic grouping seed from a phase-3A fallback.

    Phase 3B deliberately returns the independently validated one-batch-per-run
    phase-3A solution when its own optimization reaches a time limit. Building
    a complete transition graph over hundreds of those singleton loads would
    make phase 3C needlessly quadratic. This helper only creates a grouping
    *seed*: it doesn't claim to be a phase-3B result, and the resulting phase-3C
    schedule still has to pass the independent solution validator.
    """

    steps = {item.id: item for item in schedulable_steps(instance)}
    recipes = {item.id: item for item in instance.recipes}
    programs = {item.id: item for item in instance.furnace_programs}
    equipment = {item.id: item for item in instance.equipment}
    indexed_capabilities = capability_index(instance)
    assignments = {item.task_id: item for item in reference.assignments}
    frozen_ids = {item.id for item in instance.frozen_furnace_loads}
    frozen_task_ids = {
        task_id
        for item in instance.frozen_furnace_loads
        for task_id in item.member_task_ids
    }
    protected_task_ids = set(frozen_task_ids)
    pending = list(frozen_task_ids)
    while pending:
        task_id = pending.pop()
        task = steps.get(task_id)
        if task is None:
            continue
        for predecessor_id in task.predecessor_ids:
            predecessor = steps.get(predecessor_id)
            if (
                predecessor is not None
                and predecessor.stage in FURNACE_STAGES
                and predecessor_id not in protected_task_ids
            ):
                protected_task_ids.add(predecessor_id)
                pending.append(predecessor_id)

    # Frozen and started loads remain byte-for-byte identifiable. They are
    # excluded from every candidate bin, so no new member can be appended.
    # Upstream furnace ancestors are preserved as well: aggregating them can
    # move their end beyond a frozen successor's immutable start.
    preserved_loads = [
        item
        for item in reference.furnace_loads
        if item.load_id in frozen_ids
        or item.frozen
        or any(task_id in protected_task_ids for task_id in item.member_task_ids)
    ]
    new_loads = list(preserved_loads)
    assignment_updates = {}
    for stage in FURNACE_STAGES:
        grouped_steps = defaultdict(list)
        for step in steps.values():
            if step.stage != stage or step.id in protected_task_ids:
                continue
            recipe = recipes.get(step.recipe_id)
            program_id = recipe.furnace_program_id if recipe else None
            if not program_id or program_id not in programs:
                raise ModelBuildError(
                    f"Furnace task {step.id} has no executable furnace program"
                )
            # Keep successors of the same upstream furnace load together. This
            # is the temporal pre-grouping boundary: it prevents a sintering
            # load from mixing batches released by widely separated debinding
            # loads and thereby violating maximum-wait constraints.
            predecessor_cohort = tuple(
                sorted(
                    (
                        assignment_updates.get(
                            predecessor_id, assignments[predecessor_id]
                        ).furnace_load_id
                        or f"task:{predecessor_id}"
                    )
                    for predecessor_id in step.predecessor_ids
                    if steps[predecessor_id].stage in FURNACE_STAGES
                )
            )
            grouped_steps[
                (program_id, step.duration_minutes, predecessor_cohort)
            ].append(step)

        for (program_id, duration, _cohort), values in sorted(grouped_steps.items()):
            bins = []
            for step in sorted(
                values,
                key=lambda item: (
                    assignments[item.id].start_minute,
                    item.id,
                ),
            ):
                selected = None
                for candidate in bins:
                    if len(candidate["members"]) >= MAX_PREAGGREGATED_MEMBERS_PER_LOAD:
                        continue
                    if any(
                        cpsat._pair_evidence(instance, step, other) is None
                        for other in candidate["members"]
                    ):
                        continue
                    members = tuple(candidate["members"]) + (step,)
                    resources = _candidate_resources(
                        instance,
                        members,
                        duration,
                        indexed_capabilities,
                    )
                    if resources:
                        selected = candidate
                        selected["members"].append(step)
                        selected["resources"] = resources
                        break
                if selected is None:
                    resources = _candidate_resources(
                        instance,
                        (step,),
                        duration,
                        indexed_capabilities,
                    )
                    if not resources:
                        raise ModelBuildError(
                            f"Furnace task {step.id} has no capacity-feasible resource"
                        )
                    bins.append({"members": [step], "resources": resources})

            for candidate in bins:
                members = tuple(sorted(candidate["members"], key=lambda item: item.id))
                resource_counts = defaultdict(int)
                for member in members:
                    resource_counts[assignments[member.id].resource_id] += 1
                resource_id = min(
                    candidate["resources"],
                    key=lambda item: (-resource_counts[item], item),
                )
                requirements = [
                    load_requirement(member, resource_id) for member in members
                ]
                if any(item is None or item.quantity is None for item in requirements):
                    raise ModelBuildError(
                        "Preaggregation encountered an unresolved load conversion"
                    )
                loaded_quantity = sum(item.quantity for item in requirements)
                resource = equipment[resource_id]
                capacity = int(resource.capacity)
                member_task_ids = tuple(item.id for item in members)
                member_batch_ids = tuple(sorted({item.batch_id for item in members}))
                member_recipe_ids = tuple(sorted({item.recipe_id for item in members}))
                recipe_id = (
                    member_recipe_ids[0] if len(member_recipe_ids) == 1 else None
                )
                recipe = recipes.get(recipe_id)
                program = programs[program_id]
                digest = hashlib.sha256(
                    (
                        f"{stage}|{program_id}|{duration}|" + "|".join(member_task_ids)
                    ).encode("utf-8")
                ).hexdigest()[:20]
                load_id = f"phase3c-preagg:{stage}:{digest}"
                start_minute = min(
                    assignments[item.id].start_minute for item in members
                )
                compatibility_evidence = {}
                for member in members:
                    compatibility_evidence[member.batch_id] = tuple(
                        sorted(
                            f"{other.batch_id}:"
                            f"{cpsat._pair_evidence(instance, member, other)}"
                            for other in members
                            if other.id != member.id
                        )
                    )
                    assignment_updates[member.id] = replace(
                        assignments[member.id],
                        resource_id=resource_id,
                        start_minute=start_minute,
                        end_minute=start_minute + duration,
                        furnace_load_id=load_id,
                    )
                new_loads.append(
                    FurnaceLoadAssignment(
                        load_id=load_id,
                        operation_type=stage,
                        equipment_id=resource_id,
                        recipe_id=recipe_id,
                        recipe_version=recipe.version if recipe else None,
                        furnace_program_key=program.program_key,
                        start_minute=start_minute,
                        end_minute=start_minute + duration,
                        capacity=capacity,
                        loaded_quantity=loaded_quantity,
                        load_unit=requirements[0].load_unit,
                        utilization=(Decimal(loaded_quantity) / Decimal(capacity)),
                        member_batch_ids=member_batch_ids,
                        member_task_ids=member_task_ids,
                        compatibility_evidence=compatibility_evidence,
                        conversion_evidence={
                            member.batch_id: cpsat._conversion_trace(
                                member, resource_id
                            )
                            for member in members
                        },
                        frozen=False,
                        status="proposed",
                        constraint_summary={
                            "preaggregation_only": True,
                            "pairwise_compatible": True,
                            "capacity_feasible": loaded_quantity <= capacity,
                            "candidate_resource_ids": candidate["resources"],
                            "predecessor_cohort": _cohort,
                            "member_limit": (MAX_PREAGGREGATED_MEMBERS_PER_LOAD),
                        },
                        furnace_program_id=program_id,
                        furnace_program_version=program.version,
                        member_recipe_ids=member_recipe_ids,
                    )
                )

    return replace(
        reference,
        assignments=tuple(
            sorted(
                (
                    assignment_updates.get(item.task_id, item)
                    for item in reference.assignments
                ),
                key=lambda item: item.task_id,
            )
        ),
        furnace_loads=tuple(sorted(new_loads, key=lambda item: item.load_id)),
        message=(
            reference.message
            + " Phase-3C used a deterministic, validator-gated grouping seed."
        ).strip(),
    )


def _add_segment_membership(
    model,
    interval_start,
    interval_end,
    duration,
    presence,
    resource,
    horizon,
    name,
):
    segments = [
        (start, end)
        for start, end in available_segments(resource, horizon)
        if start + duration <= end
    ]
    values = []
    for number, (segment_start, segment_end) in enumerate(segments, 1):
        selected = model.NewBoolVar(f"{name}:segment:{number}")
        model.Add(interval_start >= segment_start).OnlyEnforceIf(selected)
        model.Add(interval_end <= segment_end).OnlyEnforceIf(selected)
        values.append(selected)
    if values:
        model.Add(sum(values) == presence)
    else:
        model.Add(presence == 0)


def _build_model(
    instance,
    reference,
    fixed_reference_sequence=False,
    rule_snapshot=None,
):
    horizon = instance.window.horizon_minutes
    rule_snapshot = rule_snapshot or transition_rule_snapshot(instance)
    steps = tuple(schedulable_steps(instance))
    if horizon <= 0 or not steps:
        raise ModelBuildError("Planning horizon and schedulable tasks are required")
    phase3a._validate_identity(instance, steps)

    reference_assignments = {item.task_id: item for item in reference.assignments}
    reference_loads = {item.load_id: item for item in reference.furnace_loads}
    if set(reference_assignments) != {item.id for item in steps}:
        raise ModelBuildError("Phase-3B reference does not assign every task")

    model = cp_model.CpModel()
    equipment = {item.id: item for item in instance.equipment}
    recipes = {item.id: item for item in instance.recipes}
    programs = {item.id: item for item in instance.furnace_programs}
    indexed_capabilities = capability_index(instance)
    steps_by_id = {item.id: item for item in steps}
    starts = {}
    ends = {}
    resource_choices = defaultdict(list)
    intervals_by_resource = defaultdict(list)

    for step in steps:
        start = model.NewIntVar(0, horizon, f"start:{step.id}")
        end = model.NewIntVar(0, horizon, f"end:{step.id}")
        model.Add(end == start + step.duration_minutes)
        model.Add(start >= material_ready_minute(instance, step))
        starts[step.id] = start
        ends[step.id] = end

    for step in (item for item in steps if item.stage not in FURNACE_STAGES):
        reference_assignment = reference_assignments[step.id]
        resource_id = reference_assignment.resource_id
        if resource_id not in eligible_resources(instance, step, indexed_capabilities):
            raise ModelBuildError(
                f"Reference resource {resource_id} is not eligible for {step.id}"
            )
        resource = equipment[resource_id]
        interval = model.NewIntervalVar(
            starts[step.id],
            step.duration_minutes,
            ends[step.id],
            f"task-interval:{step.id}:{resource_id}",
        )
        intervals_by_resource[resource_id].append(interval)
        present = model.NewConstant(1)
        _add_segment_membership(
            model,
            starts[step.id],
            ends[step.id],
            step.duration_minutes,
            present,
            resource,
            horizon,
            f"task:{step.id}:{resource_id}",
        )
        resource_choices[step.id].append((present, resource_id))
        model.AddHint(starts[step.id], reference_assignment.start_minute)
        if step.frozen or step.started:
            if (
                step.assigned_resource_id != resource_id
                or step.original_start_minute is None
                or step.original_end_minute is None
            ):
                raise ModelBuildError(
                    f"Frozen task {step.id} has incomplete reference data"
                )
            model.Add(starts[step.id] == step.original_start_minute)
            model.Add(ends[step.id] == step.original_end_minute)

    if fixed_reference_sequence:
        normal_by_resource = defaultdict(list)
        for step in (item for item in steps if item.stage not in FURNACE_STAGES):
            assignment = reference_assignments[step.id]
            normal_by_resource[assignment.resource_id].append(
                (assignment.start_minute, assignment.end_minute, step.id)
            )
        for values in normal_by_resource.values():
            ordered = sorted(values)
            for previous, current in zip(ordered, ordered[1:]):
                model.Add(starts[current[2]] >= ends[previous[2]])

    furnace_task_ids = {item.id for item in steps if item.stage in FURNACE_STAGES}
    membership = defaultdict(list)
    frozen_loads = {item.id: item for item in instance.frozen_furnace_loads}
    load_nodes = []
    for base in sorted(reference_loads.values(), key=lambda item: item.load_id):
        member_ids = tuple(sorted(base.member_task_ids))
        if not member_ids or any(item not in furnace_task_ids for item in member_ids):
            raise ModelBuildError(
                f"Reference furnace load {base.load_id} has invalid members"
            )
        members = tuple(steps_by_id[item] for item in member_ids)
        stages = {item.stage for item in members}
        durations = {item.duration_minutes for item in members}
        program_ids = {recipes[item.recipe_id].furnace_program_id for item in members}
        if len(stages) != 1 or len(durations) != 1 or len(program_ids) != 1:
            raise ModelBuildError(
                f"Reference furnace load {base.load_id} mixes stage, duration or program"
            )
        program_id = next(iter(program_ids))
        if not program_id or program_id not in programs:
            raise ModelBuildError(
                f"Reference furnace load {base.load_id} has no executable program"
            )
        stage = next(iter(stages))
        if programs[program_id].stage != stage:
            raise ModelBuildError(f"Furnace program stage differs for {base.load_id}")
        duration = next(iter(durations))
        candidates = _candidate_resources(
            instance, members, duration, indexed_capabilities
        )
        frozen = base.load_id in frozen_loads
        if frozen:
            original = frozen_loads[base.load_id]
            if (
                tuple(sorted(original.member_task_ids)) != member_ids
                or original.furnace_program_id != program_id
            ):
                raise ModelBuildError(
                    f"Frozen furnace load {base.load_id} differs from its reference"
                )
            candidates = (
                (original.resource_id,) if original.resource_id in candidates else ()
            )
        if not candidates:
            raise ModelBuildError(
                f"Furnace load {base.load_id} has no feasible candidate resource"
            )

        start = model.NewIntVar(0, horizon, f"load-start:{base.load_id}")
        end = model.NewIntVar(0, horizon, f"load-end:{base.load_id}")
        model.Add(end == start + duration)
        resource_values = []
        for resource_id in candidates:
            present = model.NewBoolVar(f"load-resource:{base.load_id}:{resource_id}")
            interval = model.NewOptionalIntervalVar(
                start,
                duration,
                end,
                present,
                f"load-interval:{base.load_id}:{resource_id}",
            )
            intervals_by_resource[resource_id].append(interval)
            _add_segment_membership(
                model,
                start,
                end,
                duration,
                present,
                equipment[resource_id],
                horizon,
                f"load:{base.load_id}:{resource_id}",
            )
            model.AddHint(present, int(resource_id == base.equipment_id))
            resource_values.append((present, resource_id))
        model.Add(sum(value for value, _ in resource_values) == 1)
        model.AddHint(start, base.start_minute)
        if frozen:
            original = frozen_loads[base.load_id]
            model.Add(start == original.start_minute)
            model.Add(end == original.end_minute)

        for step in members:
            model.Add(starts[step.id] == start)
            model.Add(ends[step.id] == end)
            resource_choices[step.id].extend(resource_values)
            membership[step.id].append(base.load_id)
        load_nodes.append(
            _LoadNode(
                load_id=base.load_id,
                base=base,
                stage=stage,
                duration=duration,
                member_task_ids=member_ids,
                furnace_program_id=program_id,
                start=start,
                end=end,
                resources=tuple(resource_values),
                frozen=frozen,
            )
        )

    for task_id in sorted(furnace_task_ids):
        if len(membership[task_id]) != 1:
            raise ModelBuildError(
                f"Furnace task {task_id} must belong to exactly one reference load"
            )

    states = {item.resource_id: item for item in instance.furnace_state_snapshots}
    frozen_transitions = {
        item.successor_load_id: item for item in instance.frozen_furnace_transitions
    }
    transition_arcs = []
    arc_by_key = {}
    for resource_id in sorted(equipment):
        resource_nodes = [
            item
            for item in load_nodes
            if any(candidate == resource_id for _, candidate in item.resources)
        ]
        if not resource_nodes:
            continue
        state = states.get(resource_id)
        if state is None:
            raise ModelBuildError(
                f"Furnace resource {resource_id} has no initial state"
            )
        index_by_load = {
            item.load_id: number
            for number, item in enumerate(
                sorted(resource_nodes, key=lambda item: item.load_id), 1
            )
        }
        resource_nodes = sorted(resource_nodes, key=lambda item: item.load_id)
        preferred_nodes = sorted(
            (item for item in resource_nodes if item.base.equipment_id == resource_id),
            key=lambda item: (
                item.base.start_minute,
                item.base.end_minute,
                item.load_id,
            ),
        )
        preferred_ids = [item.load_id for item in preferred_nodes]
        preferred_predecessor = {
            load_id: (preferred_ids[index - 1] if index else None)
            for index, load_id in enumerate(preferred_ids)
        }
        preferred_successor = {
            load_id: (
                preferred_ids[index + 1] if index + 1 < len(preferred_ids) else None
            )
            for index, load_id in enumerate(preferred_ids)
        }
        assignment_by_load = {
            item.load_id: next(
                value for value, candidate in item.resources if candidate == resource_id
            )
            for item in resource_nodes
        }
        circuit = []
        empty = model.NewBoolVar(f"circuit-empty:{resource_id}")
        circuit.append((0, 0, empty))
        model.AddHint(empty, int(not preferred_ids))
        assigned_total = sum(assignment_by_load.values())
        model.Add(assigned_total == 0).OnlyEnforceIf(empty)
        model.Add(assigned_total >= 1).OnlyEnforceIf(empty.Not())

        for node in resource_nodes:
            assigned = assignment_by_load[node.load_id]
            self_loop = model.NewBoolVar(f"circuit-self:{resource_id}:{node.load_id}")
            model.Add(self_loop + assigned == 1)
            model.AddHint(self_loop, int(node.load_id not in preferred_ids))
            circuit.append(
                (
                    index_by_load[node.load_id],
                    index_by_load[node.load_id],
                    self_loop,
                )
            )

            last = model.NewBoolVar(f"circuit-last:{resource_id}:{node.load_id}")
            model.Add(last <= assigned)
            model.AddHint(
                last,
                int(
                    node.load_id in preferred_ids
                    and preferred_successor[node.load_id] is None
                ),
            )
            circuit.append((index_by_load[node.load_id], 0, last))

            resolution = resolve_transition_rule(
                instance,
                resource_id,
                node.stage,
                state.state_key,
                node.furnace_program_id,
                rule_snapshot,
            )
            if resolution.allowed:
                first = model.NewBoolVar(f"circuit-first:{resource_id}:{node.load_id}")
                model.Add(first <= assigned)
                model.AddHint(
                    first,
                    int(
                        node.load_id in preferred_ids
                        and preferred_predecessor[node.load_id] is None
                    ),
                )
                circuit.append((0, index_by_load[node.load_id], first))
                arc_by_key[(resource_id, None, node.load_id)] = first
                transition_arcs.append(
                    _make_transition_arc(
                        instance,
                        model,
                        intervals_by_resource,
                        equipment[resource_id],
                        first,
                        resource_id,
                        None,
                        node,
                        state,
                        resolution,
                        frozen_transitions.get(node.load_id),
                    )
                )

        for predecessor in resource_nodes:
            predecessor_program = programs[predecessor.furnace_program_id]
            for successor in resource_nodes:
                if predecessor.load_id == successor.load_id:
                    continue
                resolution = resolve_transition_rule(
                    instance,
                    resource_id,
                    successor.stage,
                    predecessor_program.resulting_post_state_key,
                    successor.furnace_program_id,
                    rule_snapshot,
                )
                if (
                    not resolution.allowed
                    or predecessor.duration
                    + successor.duration
                    + resolution.rule.duration_minutes
                    > horizon
                ):
                    continue
                selected = model.NewBoolVar(
                    "circuit-arc:"
                    f"{resource_id}:{predecessor.load_id}:{successor.load_id}"
                )
                model.Add(selected <= assignment_by_load[predecessor.load_id])
                model.Add(selected <= assignment_by_load[successor.load_id])
                model.AddHint(
                    selected,
                    int(
                        predecessor.load_id in preferred_ids
                        and preferred_successor[predecessor.load_id]
                        == successor.load_id
                    ),
                )
                circuit.append(
                    (
                        index_by_load[predecessor.load_id],
                        index_by_load[successor.load_id],
                        selected,
                    )
                )
                arc_by_key[(resource_id, predecessor.load_id, successor.load_id)] = (
                    selected
                )
                transition_arcs.append(
                    _make_transition_arc(
                        instance,
                        model,
                        intervals_by_resource,
                        equipment[resource_id],
                        selected,
                        resource_id,
                        predecessor,
                        successor,
                        state,
                        resolution,
                        frozen_transitions.get(successor.load_id),
                    )
                )
        model.AddCircuit(circuit)
        if fixed_reference_sequence:
            for node in resource_nodes:
                model.Add(
                    assignment_by_load[node.load_id]
                    == int(node.load_id in preferred_ids)
                )
            if preferred_ids:
                required_keys = [(resource_id, None, preferred_ids[0])] + [
                    (resource_id, left, right)
                    for left, right in zip(preferred_ids, preferred_ids[1:])
                ]
                for key in required_keys:
                    if key not in arc_by_key:
                        raise ModelBuildError(
                            "Phase-3B reference order has no allowed phase-3C "
                            f"transition arc: {key}"
                        )
                    model.Add(arc_by_key[key] == 1)

    for frozen_transition in instance.frozen_furnace_transitions:
        key = (
            frozen_transition.resource_id,
            frozen_transition.predecessor_load_id,
            frozen_transition.successor_load_id,
        )
        if key not in arc_by_key:
            raise ModelBuildError(
                f"Frozen transition {frozen_transition.id} has no legal arc"
            )
        model.Add(arc_by_key[key] == 1)

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

    by_batch = defaultdict(list)
    for step in steps:
        by_batch[step.batch_id].append(step)
    final_end_by_batch = {}
    for batch_id, batch_steps in by_batch.items():
        maximum_sequence = max(item.sequence for item in batch_steps)
        final_end_by_batch[batch_id] = [
            ends[item.id] for item in batch_steps if item.sequence == maximum_sequence
        ]
    weights = cpsat._priority_weights(instance.customer_orders)
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
    transition_minutes = sum(
        item.presence * item.rule.duration_minutes for item in transition_arcs
    )
    makespan = model.NewIntVar(0, horizon, "makespan")
    model.AddMaxEquality(makespan, list(ends.values()))
    return _Artifacts(
        model=model,
        steps=steps,
        starts=starts,
        ends=ends,
        resource_choices=dict(resource_choices),
        loads=tuple(load_nodes),
        transition_arcs=tuple(transition_arcs),
        order_variables=order_variables,
        weighted_tardiness=weighted_tardiness,
        transition_minutes=transition_minutes,
        makespan=makespan,
        transition_rule_snapshot=rule_snapshot,
    )


def _make_transition_arc(
    instance,
    model,
    intervals_by_resource,
    resource,
    presence,
    resource_id,
    predecessor,
    successor,
    state,
    resolution,
    frozen_transition,
):
    rule = resolution.rule
    duration = rule.duration_minutes
    start = model.NewIntVar(
        0,
        instance.window.horizon_minutes,
        f"transition-start:{resource_id}:{predecessor.load_id if predecessor else 'initial'}:{successor.load_id}",
    )
    end = model.NewIntVar(
        0,
        instance.window.horizon_minutes,
        f"transition-end:{resource_id}:{predecessor.load_id if predecessor else 'initial'}:{successor.load_id}",
    )
    model.Add(end == start + duration).OnlyEnforceIf(presence)
    ready = predecessor.end if predecessor else state.available_minute
    model.Add(start >= ready).OnlyEnforceIf(presence)
    model.Add(end <= successor.start).OnlyEnforceIf(presence)

    matches_frozen = (
        frozen_transition is not None
        and frozen_transition.resource_id == resource_id
        and frozen_transition.predecessor_load_id
        == (predecessor.load_id if predecessor else None)
        and frozen_transition.successor_load_id == successor.load_id
        and frozen_transition.transition_rule_id == rule.id
    )
    if matches_frozen:
        model.Add(start == frozen_transition.start_minute).OnlyEnforceIf(presence)
        model.Add(end == frozen_transition.end_minute).OnlyEnforceIf(presence)
        transition_id = frozen_transition.id
    else:
        model.Add(end == successor.start).OnlyEnforceIf(presence)
        transition_id = (
            f"furnace_transition:{resource_id}:"
            f"{predecessor.load_id if predecessor else 'initial'}:"
            f"{successor.load_id}"
        )

    interval = model.NewOptionalIntervalVar(
        start,
        duration,
        end,
        presence,
        f"transition-interval:{transition_id}",
    )
    intervals_by_resource[resource_id].append(interval)
    _add_segment_membership(
        model,
        start,
        end,
        duration,
        presence,
        resource,
        instance.window.horizon_minutes,
        f"transition:{transition_id}",
    )
    from_state_key = (
        next(
            item.resulting_post_state_key
            for item in instance.furnace_programs
            if predecessor and item.id == predecessor.furnace_program_id
        )
        if predecessor
        else state.state_key
    )
    return _TransitionArc(
        presence=presence,
        resource_id=resource_id,
        predecessor_load_id=predecessor.load_id if predecessor else None,
        successor_load_id=successor.load_id,
        initial_state_id=None if predecessor else state.id,
        from_state_key=from_state_key,
        rule=rule,
        start=start,
        end=end,
        frozen=matches_frozen,
        transition_id=transition_id,
    )


def _snapshot(instance, artifacts, solver):
    steps = {item.id: item for item in artifacts.steps}
    recipes = {item.id: item for item in instance.recipes}
    programs = {item.id: item for item in instance.furnace_programs}
    equipment = {item.id: item for item in instance.equipment}
    batches = {item.id: item for item in instance.batches}

    chosen_transitions = []
    predecessor_by_load = {}
    successor_by_load = {}
    setup_by_load = {}
    for arc in sorted(
        artifacts.transition_arcs,
        key=lambda item: (
            item.resource_id,
            item.predecessor_load_id or "",
            item.successor_load_id,
        ),
    ):
        if not solver.BooleanValue(arc.presence):
            continue
        predecessor_by_load[arc.successor_load_id] = arc.predecessor_load_id
        if arc.predecessor_load_id:
            successor_by_load[arc.predecessor_load_id] = arc.successor_load_id
        setup_by_load[arc.successor_load_id] = arc.rule.duration_minutes
        chosen_transitions.append(
            FurnaceTransitionAssignment(
                transition_id=arc.transition_id,
                equipment_id=arc.resource_id,
                predecessor_load_id=arc.predecessor_load_id,
                initial_state_id=arc.initial_state_id,
                successor_load_id=arc.successor_load_id,
                from_state_key=arc.from_state_key,
                to_program_key=programs[
                    next(
                        item.furnace_program_id
                        for item in artifacts.loads
                        if item.load_id == arc.successor_load_id
                    )
                ].program_key,
                rule_id=arc.rule.id,
                rule_scope_level=arc.rule.scope_level,
                transition_type=arc.rule.transition_type,
                start_minute=solver.Value(arc.start),
                end_minute=solver.Value(arc.end),
                duration_minutes=arc.rule.duration_minutes,
                frozen=arc.frozen,
                status="proposed",
                resolution_evidence={
                    "scope_level": arc.rule.scope_level,
                    "priority": arc.rule.priority,
                    "default_if_missing": "forbid",
                    "rule_id": arc.rule.id,
                    "transition_rule_resolution_mode": (
                        artifacts.transition_rule_snapshot.resolution_mode
                    ),
                    "transition_rule_snapshot_at": (
                        artifacts.transition_rule_snapshot.snapshot_at
                    ),
                    "transition_rule_snapshot_fingerprint": (
                        artifacts.transition_rule_snapshot.fingerprint
                    ),
                },
            )
        )

    furnace_loads = []
    task_load = {}
    for node in sorted(artifacts.loads, key=lambda item: item.load_id):
        resource_id = next(
            resource_id
            for presence, resource_id in node.resources
            if solver.BooleanValue(presence)
        )
        member_steps = [steps[item] for item in node.member_task_ids]
        member_recipe_ids = tuple(sorted({item.recipe_id for item in member_steps}))
        recipe_id = member_recipe_ids[0] if len(member_recipe_ids) == 1 else None
        recipe = recipes[recipe_id] if recipe_id else None
        program = programs[node.furnace_program_id]
        requirements = [load_requirement(item, resource_id) for item in member_steps]
        loaded_quantity = sum(item.quantity for item in requirements)
        capacity = int(equipment[resource_id].capacity)
        compatibility_evidence = {}
        for step in member_steps:
            values = []
            for other in member_steps:
                if other.id == step.id:
                    continue
                values.append(
                    f"{batches[other.batch_id].id}:"
                    f"{cpsat._pair_evidence(instance, step, other)}"
                )
            compatibility_evidence[step.batch_id] = tuple(sorted(values))
            task_load[step.id] = node.load_id
        furnace_loads.append(
            replace(
                node.base,
                equipment_id=resource_id,
                recipe_id=recipe_id,
                recipe_version=recipe.version if recipe else None,
                furnace_program_key=program.program_key,
                start_minute=solver.Value(node.start),
                end_minute=solver.Value(node.end),
                capacity=capacity,
                loaded_quantity=loaded_quantity,
                load_unit=requirements[0].load_unit,
                utilization=Decimal(loaded_quantity) / Decimal(capacity),
                member_batch_ids=tuple(
                    sorted({item.batch_id for item in member_steps})
                ),
                member_task_ids=node.member_task_ids,
                compatibility_evidence=compatibility_evidence,
                conversion_evidence={
                    item.batch_id: cpsat._conversion_trace(item, resource_id)
                    for item in member_steps
                },
                frozen=node.frozen,
                furnace_program_id=node.furnace_program_id,
                furnace_program_version=program.version,
                member_recipe_ids=member_recipe_ids,
                predecessor_load_id=predecessor_by_load.get(node.load_id),
                successor_load_id=successor_by_load.get(node.load_id),
                setup_before_minutes=setup_by_load.get(node.load_id, 0),
                constraint_summary={
                    **node.base.constraint_summary,
                    "transition_sequence_feasible": True,
                    "furnace_program_id": node.furnace_program_id,
                },
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
                task_id=task_id,
                batch_id=step.batch_id,
                stage=step.stage,
                resource_id=resource_id,
                start_minute=solver.Value(artifacts.starts[task_id]),
                end_minute=solver.Value(artifacts.ends[task_id]),
                frozen=step.frozen or step.started,
                furnace_load_id=task_load.get(task_id),
            )
        )

    orders_by_id = {item.id: item for item in instance.customer_orders}
    orders = []
    for order_id in sorted(artifacts.order_variables):
        completion, tardiness, weight = artifacts.order_variables[order_id]
        order = orders_by_id[order_id]
        tardiness_value = solver.Value(tardiness)
        orders.append(
            OrderSchedule(
                order_id=order_id,
                completion_minute=solver.Value(completion),
                due_minute=order.due_minute,
                tardiness_minutes=tardiness_value,
                priority=order.priority,
                priority_weight=weight,
                weighted_tardiness=tardiness_value * weight,
            )
        )
    return (
        tuple(assignments),
        tuple(furnace_loads),
        tuple(chosen_transitions),
        tuple(orders),
    )


def _reference_valid_under_phase3c(instance, reference, rule_snapshot=None):
    rule_snapshot = rule_snapshot or transition_rule_snapshot(instance)
    programs = {item.id: item for item in instance.furnace_programs}
    states = {item.resource_id: item for item in instance.furnace_state_snapshots}
    by_resource = defaultdict(list)
    for load in reference.furnace_loads:
        by_resource[load.equipment_id].append(load)
    for resource_id, loads in by_resource.items():
        state = states.get(resource_id)
        if state is None:
            return False
        previous = None
        for load in sorted(loads, key=lambda item: (item.start_minute, item.load_id)):
            program_id = load.furnace_program_id
            program = programs.get(program_id)
            if program is None:
                return False
            from_state = (
                programs[previous.furnace_program_id].resulting_post_state_key
                if previous
                else state.state_key
            )
            resolution = resolve_transition_rule(
                instance,
                resource_id,
                load.operation_type,
                from_state,
                program_id,
                rule_snapshot,
            )
            ready = previous.end_minute if previous else state.available_minute
            if (
                not resolution.allowed
                or load.start_minute < ready + resolution.rule.duration_minutes
            ):
                return False
            transition_start = load.start_minute - resolution.rule.duration_minutes
            resource = next(
                item for item in instance.equipment if item.id == resource_id
            )
            if not any(
                start <= transition_start and load.start_minute <= end
                for start, end in available_segments(
                    resource, instance.window.horizon_minutes
                )
            ):
                return False
            previous = load
    return True


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
        name=name,
        status=_status_name(status),
        value=value,
        best_bound=bound,
        wall_time_seconds=round(solver.WallTime(), 6),
    )


def _metrics(solution):
    base = cpsat._metrics(solution)
    return {
        **base,
        "transition_minutes": sum(
            item.duration_minutes for item in solution.furnace_transitions
        ),
        "transition_count": len(solution.furnace_transitions),
    }


def _furnace_load_count_source(reference_provenance):
    if (
        (reference_provenance or {}).get("grouping_source")
        == "deterministic_phase3c_preaggregation"
    ):
        return "deterministic_pregrouped"
    return "phase3b_inherited"


def _finalize(
    instance,
    parameters,
    snapshot,
    rule_snapshot,
    stages,
    started,
    reference_metrics,
    reference_valid,
    reference_provenance=None,
    fallback_reason=None,
):
    assignments, loads, transitions, orders = snapshot
    stage_gaps = [
        abs(item.value - item.best_bound) / max(1, abs(item.value))
        for item in stages
        if item.value is not None and item.best_bound is not None
    ]
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
        furnace_transitions=transitions,
        orders=orders,
        objective_stages=tuple(stages),
        objective_values={
            "weighted_tardiness": sum(item.weighted_tardiness for item in orders),
            "furnace_load_count": len(loads),
            "transition_minutes": sum(item.duration_minutes for item in transitions),
            "makespan": max((item.end_minute for item in assignments), default=0),
        },
        wall_time_seconds=round(perf_counter() - started, 6),
        optimality_gap=max(stage_gaps) if stage_gaps else None,
        message=(
            "Phase-3C sequence-dependent furnace transition solution."
            if not fallback_reason
            else (
                "Phase-3C validated intermediate solution returned after "
                f"{fallback_reason}."
            )
        ),
        solution_mode="phase3c_transition",
        fallback_reason=fallback_reason,
        last_successful_stage=next(
            (
                item.name
                for item in reversed(stages)
                if item.status in ("FEASIBLE", "OPTIMAL")
            ),
            None,
        ),
    )
    phase3c_metrics = {
        **_metrics(solution),
        "furnace_load_count_source": _furnace_load_count_source(
            reference_provenance
        ),
        "furnace_load_count_optimized": False,
        "transition_rule_resolution_mode": rule_snapshot.resolution_mode,
        "transition_rule_snapshot_at": rule_snapshot.snapshot_at,
        "transition_rule_snapshot_fingerprint": rule_snapshot.fingerprint,
        "effective_transition_rule_ids": rule_snapshot.effective_rule_ids,
        "selected_transition_rule_ids": tuple(
            sorted({item.rule_id for item in transitions})
        ),
    }
    phase3b_reference_metrics = {
        **reference_metrics,
        "valid_under_phase3c_constraints": reference_valid,
        **(reference_provenance or {}),
    }
    setup_cost = sum(
        (
            next(
                rule.setup_cost
                for rule in instance.furnace_transition_rules
                if rule.id == transition.rule_id
            )
            for transition in transitions
        ),
        Decimal("0"),
    )
    return replace(
        solution,
        phase3a_baseline_metrics={},
        phase3b_metrics=reference_metrics,
        phase3b_reference_metrics=phase3b_reference_metrics,
        phase3c_metrics=phase3c_metrics,
        transition_constraint_cost={
            "total_duration_minutes": phase3c_metrics["transition_minutes"],
            "setup_cost": setup_cost,
            "setup_cost_unit": "source_rule_unit",
        },
        metric_deltas={
            "weighted_tardiness": (
                phase3c_metrics["weighted_tardiness"]
                - reference_metrics["weighted_tardiness"]
            ),
            "furnace_load_count": (
                phase3c_metrics["furnace_load_count"]
                - reference_metrics["furnace_load_count"]
            ),
            "makespan": (phase3c_metrics["makespan"] - reference_metrics["makespan"]),
            "transition_minutes": phase3c_metrics["transition_minutes"],
        },
    )


def _empty_solution(
    instance,
    parameters,
    started,
    status,
    message,
    reference_metrics=None,
    last_successful_stage=None,
):
    rule_snapshot = transition_rule_snapshot(instance)
    return SchedulingSolution(
        status=status,
        input_fingerprint=planning_instance_fingerprint(instance),
        solver_name="Google OR-Tools CP-SAT",
        solver_version=ortools.__version__,
        parameters=parameters,
        wall_time_seconds=round(perf_counter() - started, 6),
        message=message,
        solution_mode="phase3c_transition",
        fallback_reason=None,
        last_successful_stage=last_successful_stage,
        phase3b_reference_metrics=reference_metrics or {},
        phase3c_metrics={
            "furnace_load_count_optimized": False,
            "transition_rule_resolution_mode": rule_snapshot.resolution_mode,
            "transition_rule_snapshot_at": rule_snapshot.snapshot_at,
            "transition_rule_snapshot_fingerprint": rule_snapshot.fingerprint,
            "effective_transition_rule_ids": rule_snapshot.effective_rule_ids,
            "selected_transition_rule_ids": (),
        },
    )


def _attach_runtime_timings(solution, timings, started):
    rounded = {key: round(value, 6) for key, value in sorted(timings.items())}
    return replace(
        solution,
        wall_time_seconds=round(perf_counter() - started, 6),
        phase3c_metrics={
            **solution.phase3c_metrics,
            "timing_seconds": rounded,
        },
    )


def solve(instance, parameters=None):
    """Solve phase 3C without accessing Django ORM objects."""

    rule_snapshot = transition_rule_snapshot(instance)
    parameters = replace(
        parameters or SolverParameters(),
        furnace_mode="sequence_dependent_transitions",
    )
    report = PlanningInstanceValidator().validate(instance)
    if report.blocker_count:
        raise PrecheckBlockedError(report)
    if parameters.max_time_seconds <= 0 or parameters.num_search_workers <= 0:
        raise ValueError("Solver time and worker count must be greater than zero")

    started = perf_counter()
    timings = {
        "phase3b_reference": 0.0,
        "preaggregation": 0.0,
        "seed_model_build": 0.0,
        "free_model_build": 0.0,
        "independent_validator": 0.0,
    }
    # Reserve five percent for model construction, independent validation and
    # deterministic serialization so the end-to-end call respects the public
    # time budget instead of only limiting individual CP-SAT calls.
    solve_budget = max(0.001, parameters.max_time_seconds * 0.95)
    reference_time = min(
        60.0,
        max(1.0, solve_budget * 0.25),
    )
    reference_started = perf_counter()
    reference = cpsat.solve(
        instance,
        replace(
            parameters,
            max_time_seconds=reference_time,
            furnace_mode="multi_batch_loads",
        ),
    )
    timings["phase3b_reference"] = perf_counter() - reference_started
    if reference.status == "MODEL_INVALID":
        return _empty_solution(
            instance,
            parameters,
            started,
            "MODEL_INVALID",
            f"Phase-3B reference model is invalid: {reference.message}",
            last_successful_stage=reference.last_successful_stage,
        )
    if reference.status not in ("FEASIBLE", "OPTIMAL"):
        return _empty_solution(
            instance,
            parameters,
            started,
            reference.status,
            f"Phase-3B reference did not produce a feasible grouping: {reference.message}",
            last_successful_stage=reference.last_successful_stage,
        )
    reference_metrics = cpsat._metrics(reference)
    reference_valid = _reference_valid_under_phase3c(
        instance,
        reference,
        rule_snapshot,
    )
    grouping_reference = reference
    grouping_source = "phase3b_reference"
    if reference.solution_mode == "phase3a_fallback" or len(
        reference.furnace_loads
    ) > max(64, len(reference.assignments) // 4):
        preaggregation_started = perf_counter()
        try:
            grouping_reference = _preaggregate_reference(instance, reference)
        except (ModelBuildError, StopIteration) as exc:
            return _empty_solution(
                instance,
                parameters,
                started,
                "MODEL_INVALID",
                f"Phase-3C deterministic preaggregation failed: {exc}",
                {
                    **reference_metrics,
                    "valid_under_phase3c_constraints": reference_valid,
                    "raw_solution_mode": reference.solution_mode,
                    "raw_fallback_reason": reference.fallback_reason,
                    "grouping_source": "deterministic_preaggregation_failed",
                },
                reference.last_successful_stage,
            )
        timings["preaggregation"] = perf_counter() - preaggregation_started
        grouping_source = "deterministic_phase3c_preaggregation"
    reference_provenance = {
        "raw_solution_mode": reference.solution_mode,
        "raw_fallback_reason": reference.fallback_reason,
        "raw_furnace_load_count": len(reference.furnace_loads),
        "grouping_source": grouping_source,
        "grouping_furnace_load_count": len(grouping_reference.furnace_loads),
        "maximum_preaggregated_members_per_load": (
            MAX_PREAGGREGATED_MEMBERS_PER_LOAD
            if grouping_source == "deterministic_phase3c_preaggregation"
            else None
        ),
        "reference_solve_seconds": round(timings["phase3b_reference"], 6),
        "preaggregation_seconds": round(timings["preaggregation"], 6),
        "furnace_load_count_source": _furnace_load_count_source(
            {"grouping_source": grouping_source}
        ),
        "furnace_load_count_optimized": False,
    }

    remaining = solve_budget - (perf_counter() - started)
    if remaining <= 0.01:
        return _empty_solution(
            instance,
            parameters,
            started,
            "UNKNOWN",
            "No phase-3C solve time remained after the phase-3B reference.",
            {
                **reference_metrics,
                "valid_under_phase3c_constraints": reference_valid,
                **reference_provenance,
            },
            reference.last_successful_stage,
        )

    # First seek a strict C-level seed while fixing only the phase-3B equipment
    # and chronological load order. This model is much smaller than the free
    # adjacency model and gives the latter a validated transition-aware hint.
    seed_candidate = None
    seed_build_error = None
    seed_build_started = perf_counter()
    try:
        seed_artifacts = _build_model(
            instance,
            grouping_reference,
            fixed_reference_sequence=True,
            rule_snapshot=rule_snapshot,
        )
    except (ModelBuildError, StopIteration) as exc:
        seed_build_error = str(exc)
    else:
        timings["seed_model_build"] = perf_counter() - seed_build_started
        remaining = solve_budget - (perf_counter() - started)
        if remaining > 0.01:
            seed_solver = _configure_solver(
                parameters,
                min(60.0, max(0.01, remaining * 0.35)),
            )
            seed_status = seed_solver.Solve(seed_artifacts.model)
            if seed_status == cp_model.MODEL_INVALID:
                return _empty_solution(
                    instance,
                    parameters,
                    started,
                    "MODEL_INVALID",
                    "CP-SAT rejected the phase-3C fixed-sequence seed model.",
                    {
                        **reference_metrics,
                        "valid_under_phase3c_constraints": reference_valid,
                    },
                    reference.last_successful_stage,
                )
            if seed_status in (cp_model.FEASIBLE, cp_model.OPTIMAL):
                seed_stage = _stage_result(
                    "feasibility",
                    seed_solver,
                    seed_status,
                    None,
                )
                seed_candidate = _finalize(
                    instance,
                    parameters,
                    _snapshot(instance, seed_artifacts, seed_solver),
                    seed_artifacts.transition_rule_snapshot,
                    (seed_stage,),
                    started,
                    reference_metrics,
                    reference_valid,
                    reference_provenance,
                )
                validation_started = perf_counter()
                seed_validation = SchedulingSolutionValidator().validate(
                    instance, seed_candidate
                )
                timings["independent_validator"] += perf_counter() - validation_started
                if not seed_validation.valid:
                    return _empty_solution(
                        instance,
                        parameters,
                        started,
                        "MODEL_INVALID",
                        "Phase-3C seed failed independent validation: "
                        + "; ".join(
                            f"{item.code}:{item.object_id}"
                            for item in seed_validation.violations
                        ),
                        {
                            **reference_metrics,
                            "valid_under_phase3c_constraints": reference_valid,
                            **reference_provenance,
                        },
                        "feasibility",
                    )

    remaining = solve_budget - (perf_counter() - started)
    if remaining <= 0.01 and seed_candidate is not None:
        return _attach_runtime_timings(
            replace(
                seed_candidate,
                status="FEASIBLE",
                fallback_reason="phase3c_time_limit_after_valid_seed",
                message="Phase-3C validated fixed-sequence seed returned at time limit.",
            ),
            timings,
            started,
        )
    if remaining <= 0.01:
        return _empty_solution(
            instance,
            parameters,
            started,
            "UNKNOWN",
            "No phase-3C feasible solution was found before the time limit."
            + (f" Seed build: {seed_build_error}." if seed_build_error else ""),
            {
                **reference_metrics,
                "valid_under_phase3c_constraints": reference_valid,
                **reference_provenance,
            },
            reference.last_successful_stage,
        )

    free_build_started = perf_counter()
    try:
        artifacts = _build_model(
            instance,
            seed_candidate or grouping_reference,
            fixed_reference_sequence=False,
            rule_snapshot=rule_snapshot,
        )
    except (ModelBuildError, StopIteration) as exc:
        return _empty_solution(
            instance,
            parameters,
            started,
            "MODEL_INVALID",
            str(exc),
            {
                **reference_metrics,
                "valid_under_phase3c_constraints": reference_valid,
                **reference_provenance,
            },
            reference.last_successful_stage,
        )
    timings["free_model_build"] = perf_counter() - free_build_started

    stages = list(seed_candidate.objective_stages) if seed_candidate is not None else []
    validated_candidates = [seed_candidate] if seed_candidate is not None else []
    validation_errors = []
    objectives = (
        () if seed_candidate is not None else (("feasibility", None, 0.65),)
    ) + (
        ("weighted_tardiness", artifacts.weighted_tardiness, 0.40),
        ("transition_minutes", artifacts.transition_minutes, 0.28),
        ("makespan", artifacts.makespan, 1.0),
    )
    planned_stage_count = len(stages) + len(objectives)
    for name, objective, fraction in objectives:
        remaining = solve_budget - (perf_counter() - started)
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
        candidate = _finalize(
            instance,
            parameters,
            _snapshot(instance, artifacts, solver),
            artifacts.transition_rule_snapshot,
            stages,
            started,
            reference_metrics,
            reference_valid,
            reference_provenance,
        )
        validation_started = perf_counter()
        validation = SchedulingSolutionValidator().validate(instance, candidate)
        timings["independent_validator"] += perf_counter() - validation_started
        if validation.valid:
            validated_candidates.append(candidate)
        else:
            validation_errors = [
                f"{item.code}:{item.object_id}" for item in validation.violations
            ]
        if objective is not None:
            artifacts.model.Add(objective <= value)

    if stages and stages[-1].status == "MODEL_INVALID":
        return _empty_solution(
            instance,
            parameters,
            started,
            "MODEL_INVALID",
            "CP-SAT rejected the phase-3C model.",
            {
                **reference_metrics,
                "valid_under_phase3c_constraints": reference_valid,
                **reference_provenance,
            },
            next(
                (
                    item.name
                    for item in reversed(stages[:-1])
                    if item.status in ("FEASIBLE", "OPTIMAL")
                ),
                reference.last_successful_stage,
            ),
        )
    if not validated_candidates:
        if validation_errors:
            return _empty_solution(
                instance,
                parameters,
                started,
                "MODEL_INVALID",
                "Phase-3C snapshot failed independent validation: "
                + "; ".join(validation_errors),
                {
                    **reference_metrics,
                    "valid_under_phase3c_constraints": reference_valid,
                    **reference_provenance,
                },
                next(
                    (
                        item.name
                        for item in reversed(stages)
                        if item.status in ("FEASIBLE", "OPTIMAL")
                    ),
                    reference.last_successful_stage,
                ),
            )
        terminal_status = stages[-1].status if stages else "UNKNOWN"
        return _empty_solution(
            instance,
            parameters,
            started,
            terminal_status,
            "No phase-3C feasible solution was found.",
            {
                **reference_metrics,
                "valid_under_phase3c_constraints": reference_valid,
                **reference_provenance,
            },
            reference.last_successful_stage,
        )

    candidate = validated_candidates[-1]
    incomplete = len(stages) < planned_stage_count or stages[-1].status not in (
        "FEASIBLE",
        "OPTIMAL",
    )
    if incomplete:
        return _attach_runtime_timings(
            replace(
                candidate,
                status="FEASIBLE",
                fallback_reason="phase3c_time_limit_or_unknown_after_valid_snapshot",
                message=(
                    "Phase-3C validated intermediate solution returned because the "
                    "remaining optimization stages did not complete."
                ),
            ),
            timings,
            started,
        )
    return _attach_runtime_timings(candidate, timings, started)
