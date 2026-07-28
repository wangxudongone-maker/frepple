"""Phase-3A one-batch-per-furnace safety baseline."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from time import perf_counter

import ortools
from ortools.sat.python import cp_model

from .constraints import (
    available_segments,
    capability_index,
    eligible_resources,
    material_ready_minute,
    schedulable_steps,
)
from .serializer import planning_instance_fingerprint
from .solution import (
    ObjectiveStage,
    OrderSchedule,
    SchedulingSolution,
    SolverParameters,
    TaskAssignment,
)
from .validator import PlanningInstanceValidator


class PrecheckBlockedError(ValueError):
    def __init__(self, report):
        self.report = report
        super().__init__(
            f"MLCC precheck has {report.blocker_count} BLOCKER issue(s); "
            "CP-SAT was not started."
        )


class ModelBuildError(ValueError):
    pass


@dataclass
class _Artifacts:
    model: cp_model.CpModel
    steps: tuple
    starts: dict
    ends: dict
    alternatives: dict
    order_variables: dict
    weighted_tardiness: object
    makespan: object


def _status_name(status):
    return {
        cp_model.OPTIMAL: "OPTIMAL",
        cp_model.FEASIBLE: "FEASIBLE",
        cp_model.INFEASIBLE: "INFEASIBLE",
        cp_model.MODEL_INVALID: "MODEL_INVALID",
        cp_model.UNKNOWN: "UNKNOWN",
    }.get(status, f"STATUS_{status}")


def _priority_weights(orders):
    priorities = [max(1, order.priority) for order in orders]
    maximum = max(priorities, default=1)
    return {order.id: max(1, maximum + 1 - max(1, order.priority)) for order in orders}


def _validate_identity(instance, steps):
    collections = {
        "task": [item.id for item in steps],
        "resource": [item.id for item in instance.equipment],
        "order": [item.id for item in instance.customer_orders],
        "batch": [item.id for item in instance.batches],
    }
    for label, identifiers in collections.items():
        if len(identifiers) != len(set(identifiers)):
            raise ModelBuildError(f"Duplicate stable {label} identifier")


def _build_model(instance):
    horizon = instance.window.horizon_minutes
    if horizon <= 0:
        raise ModelBuildError("Planning horizon must be greater than zero")
    steps = schedulable_steps(instance)
    if not steps:
        raise ModelBuildError("Planning instance has no schedulable tasks")
    _validate_identity(instance, steps)

    model = cp_model.CpModel()
    starts = {}
    ends = {}
    alternatives = {}
    intervals_by_resource = defaultdict(list)
    equipment = {item.id: item for item in instance.equipment}
    indexed_capabilities = capability_index(instance)
    frozen_load_by_task = {
        task_id: load
        for load in instance.frozen_furnace_loads
        for task_id in load.member_task_ids
    }

    for step in steps:
        if step.duration_minutes <= 0:
            raise ModelBuildError(f"Task {step.id} has invalid duration")
        start = model.NewIntVar(0, horizon, f"start:{step.id}")
        end = model.NewIntVar(0, horizon, f"end:{step.id}")
        starts[step.id] = start
        ends[step.id] = end
        model.Add(end == start + step.duration_minutes)
        model.Add(start >= material_ready_minute(instance, step))

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
            if (
                step.original_end_minute - step.original_start_minute
                != step.duration_minutes
            ):
                raise ModelBuildError(
                    f"Frozen task {step.id} duration differs from original interval"
                )
            model.Add(start == step.original_start_minute)
            model.Add(end == step.original_end_minute)

        resources = eligible_resources(instance, step, indexed_capabilities)
        if fixed:
            if step.assigned_resource_id not in resources:
                raise ModelBuildError(
                    f"Frozen task {step.id} is assigned to an ineligible resource"
                )
            resources = (step.assigned_resource_id,)

        choices = []
        for resource_id in resources:
            resource = equipment[resource_id]
            for segment_number, (segment_start, segment_end) in enumerate(
                available_segments(resource, horizon),
                1,
            ):
                if fixed and not (
                    segment_start <= step.original_start_minute
                    and step.original_end_minute <= segment_end
                ):
                    continue
                lower_bound = max(
                    segment_start,
                    material_ready_minute(instance, step),
                )
                if lower_bound + step.duration_minutes > segment_end:
                    continue
                presence = model.NewBoolVar(
                    f"assign:{step.id}:{resource_id}:{segment_number}"
                )
                interval = model.NewOptionalIntervalVar(
                    start,
                    step.duration_minutes,
                    end,
                    presence,
                    f"interval:{step.id}:{resource_id}:{segment_number}",
                )
                model.Add(start >= lower_bound).OnlyEnforceIf(presence)
                model.Add(end <= segment_end).OnlyEnforceIf(presence)
                choices.append((presence, resource_id))
                frozen_load = frozen_load_by_task.get(step.id)
                if frozen_load is None or step.id == min(frozen_load.member_task_ids):
                    intervals_by_resource[resource_id].append(interval)
        alternatives[step.id] = tuple(choices)
        if choices:
            model.Add(sum(presence for presence, _ in choices) == 1)
        else:
            # Keep a structurally valid but provably infeasible model.
            model.AddBoolOr([])

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
    steps_by_batch = defaultdict(list)
    for step in steps:
        steps_by_batch[step.batch_id].append(step)
    for batch_id, batch_steps in steps_by_batch.items():
        maximum_sequence = max(item.sequence for item in batch_steps)
        final_end_by_batch[batch_id].extend(
            ends[item.id] for item in batch_steps if item.sequence == maximum_sequence
        )

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
        maximum_tardiness = max(0, horizon - due)
        tardiness = model.NewIntVar(
            0,
            maximum_tardiness,
            f"tardiness:{order.id}",
        )
        model.AddMaxEquality(tardiness, [completion - due, 0])
        weight = weights[order.id]
        weighted_terms.append(tardiness * weight)
        order_variables[order.id] = (completion, tardiness, weight)

    weighted_tardiness = sum(weighted_terms) if weighted_terms else 0
    makespan = model.NewIntVar(0, horizon, "makespan")
    model.AddMaxEquality(makespan, list(ends.values()))
    return _Artifacts(
        model=model,
        steps=steps,
        starts=starts,
        ends=ends,
        alternatives=alternatives,
        order_variables=order_variables,
        weighted_tardiness=weighted_tardiness,
        makespan=makespan,
    )


def _configure_solver(parameters, time_limit):
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(0.001, float(time_limit))
    solver.parameters.num_search_workers = parameters.num_search_workers
    solver.parameters.random_seed = parameters.random_seed
    solver.parameters.log_search_progress = parameters.log_search_progress
    return solver


def _stage_result(name, solver, status, value):
    best_bound = None
    if name != "feasibility" and status in (cp_model.FEASIBLE, cp_model.OPTIMAL):
        best_bound = float(solver.BestObjectiveBound())
    return ObjectiveStage(
        name=name,
        status=_status_name(status),
        value=value,
        best_bound=best_bound,
        wall_time_seconds=round(solver.WallTime(), 6),
    )


def _snapshot(instance, artifacts, solver):
    steps = {item.id: item for item in artifacts.steps}
    orders = {item.id: item for item in instance.customer_orders}
    assignments = []
    for task_id in sorted(artifacts.starts):
        resource_id = next(
            resource_id
            for presence, resource_id in artifacts.alternatives[task_id]
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
            )
        )
    order_schedules = []
    for order_id in sorted(artifacts.order_variables):
        completion, tardiness, weight = artifacts.order_variables[order_id]
        order = orders[order_id]
        tardiness_value = solver.Value(tardiness)
        order_schedules.append(
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
    return tuple(assignments), tuple(order_schedules)


def _terminal_solution(
    instance,
    parameters,
    status,
    started,
    stages=(),
    message="",
):
    return SchedulingSolution(
        status=status,
        input_fingerprint=planning_instance_fingerprint(instance),
        solver_name="Google OR-Tools CP-SAT",
        solver_version=ortools.__version__,
        parameters=parameters,
        objective_stages=tuple(stages),
        wall_time_seconds=round(perf_counter() - started, 6),
        message=message,
    )


def solve(instance, parameters=None):
    """Solve a pure planning instance; this module never accesses Django ORM."""

    parameters = parameters or SolverParameters()
    if parameters.max_time_seconds <= 0:
        raise ValueError("max_time_seconds must be greater than zero")
    if parameters.num_search_workers <= 0:
        raise ValueError("num_search_workers must be greater than zero")

    report = PlanningInstanceValidator().validate(instance)
    if report.blocker_count:
        raise PrecheckBlockedError(report)

    started = perf_counter()
    try:
        artifacts = _build_model(instance)
    except ModelBuildError as exc:
        return _terminal_solution(
            instance,
            parameters,
            "MODEL_INVALID",
            started,
            message=str(exc),
        )

    stages = []
    snapshots = []
    total_limit = float(parameters.max_time_seconds)

    feasibility_limit = min(total_limit, max(0.01, total_limit * 0.2))
    feasibility_solver = _configure_solver(parameters, feasibility_limit)
    status = feasibility_solver.Solve(artifacts.model)
    stages.append(_stage_result("feasibility", feasibility_solver, status, None))
    if status not in (cp_model.FEASIBLE, cp_model.OPTIMAL):
        return _terminal_solution(
            instance,
            parameters,
            _status_name(status),
            started,
            stages,
            "No strictly feasible schedule was found.",
        )
    snapshots.append(_snapshot(instance, artifacts, feasibility_solver))

    remaining = max(0.0, total_limit - (perf_counter() - started))
    if remaining <= 0.001:
        assignments, orders = snapshots[-1]
        return SchedulingSolution(
            status="FEASIBLE",
            input_fingerprint=planning_instance_fingerprint(instance),
            solver_name="Google OR-Tools CP-SAT",
            solver_version=ortools.__version__,
            parameters=parameters,
            assignments=assignments,
            orders=orders,
            objective_stages=tuple(stages),
            wall_time_seconds=round(perf_counter() - started, 6),
            message="Feasible schedule found; optimization time limit exhausted.",
        )

    artifacts.model.Minimize(artifacts.weighted_tardiness)
    tardiness_limit = max(0.001, remaining * 0.65)
    tardiness_solver = _configure_solver(parameters, tardiness_limit)
    status = tardiness_solver.Solve(artifacts.model)
    tardiness_value = (
        int(tardiness_solver.Value(artifacts.weighted_tardiness))
        if status in (cp_model.FEASIBLE, cp_model.OPTIMAL)
        else None
    )
    stages.append(
        _stage_result(
            "weighted_tardiness",
            tardiness_solver,
            status,
            tardiness_value,
        )
    )
    if status not in (cp_model.FEASIBLE, cp_model.OPTIMAL):
        assignments, orders = snapshots[-1]
        return SchedulingSolution(
            status="FEASIBLE",
            input_fingerprint=planning_instance_fingerprint(instance),
            solver_name="Google OR-Tools CP-SAT",
            solver_version=ortools.__version__,
            parameters=parameters,
            assignments=assignments,
            orders=orders,
            objective_stages=tuple(stages),
            wall_time_seconds=round(perf_counter() - started, 6),
            message="Tardiness optimization did not improve the feasible schedule.",
        )
    snapshots.append(_snapshot(instance, artifacts, tardiness_solver))
    artifacts.model.Add(artifacts.weighted_tardiness <= tardiness_value)

    remaining = max(0.0, total_limit - (perf_counter() - started))
    if remaining <= 0.001:
        assignments, orders = snapshots[-1]
        return SchedulingSolution(
            status="FEASIBLE",
            input_fingerprint=planning_instance_fingerprint(instance),
            solver_name="Google OR-Tools CP-SAT",
            solver_version=ortools.__version__,
            parameters=parameters,
            assignments=assignments,
            orders=orders,
            objective_stages=tuple(stages),
            objective_values={"weighted_tardiness": tardiness_value},
            wall_time_seconds=round(perf_counter() - started, 6),
            message="Weighted tardiness optimized; makespan time limit exhausted.",
        )

    artifacts.model.Minimize(artifacts.makespan)
    makespan_solver = _configure_solver(parameters, remaining)
    status = makespan_solver.Solve(artifacts.model)
    makespan_value = (
        int(makespan_solver.Value(artifacts.makespan))
        if status in (cp_model.FEASIBLE, cp_model.OPTIMAL)
        else None
    )
    stages.append(_stage_result("makespan", makespan_solver, status, makespan_value))
    if status in (cp_model.FEASIBLE, cp_model.OPTIMAL):
        snapshots.append(_snapshot(instance, artifacts, makespan_solver))
        final_status = (
            "OPTIMAL"
            if all(item.status == "OPTIMAL" for item in stages)
            else "FEASIBLE"
        )
    else:
        final_status = "FEASIBLE"

    assignments, orders = snapshots[-1]
    objective_values = {"weighted_tardiness": tardiness_value}
    if makespan_value is not None:
        objective_values["makespan"] = makespan_value
    gap = None
    final_stage = next(
        (
            item
            for item in stages[1:]
            if item.status != "OPTIMAL" and item.value is not None
        ),
        stages[-1],
    )
    if (
        final_stage.value is not None
        and final_stage.best_bound is not None
        and final_stage.status in ("FEASIBLE", "OPTIMAL")
    ):
        gap = abs(final_stage.value - final_stage.best_bound) / max(
            1.0, abs(final_stage.value)
        )
    return SchedulingSolution(
        status=final_status,
        input_fingerprint=planning_instance_fingerprint(instance),
        solver_name="Google OR-Tools CP-SAT",
        solver_version=ortools.__version__,
        parameters=parameters,
        assignments=assignments,
        orders=orders,
        objective_stages=tuple(stages),
        objective_values=objective_values,
        wall_time_seconds=round(perf_counter() - started, 6),
        optimality_gap=gap,
        message=(
            ""
            if status in (cp_model.FEASIBLE, cp_model.OPTIMAL)
            else "Makespan optimization returned no solution; retained prior schedule."
        ),
    )
