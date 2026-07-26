"""Independent validation of schedule output without invoking CP-SAT."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from .constraints import (
    available_segments,
    capability_index,
    eligible_resources,
    material_ready_minute,
    schedulable_steps,
)


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
    """Validate all phase-3A hard constraints using data only."""

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
            if (
                assignment.end_minute - assignment.start_minute
                != step.duration_minutes
            ):
                add(
                    "MLCC-SV008",
                    task_id,
                    "Assignment duration differs from standard duration.",
                )
            if resource and not any(
                start <= assignment.start_minute
                and assignment.end_minute <= end
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
            ordered = sorted(
                resource_assignments,
                key=lambda item: (item.start_minute, item.end_minute, item.task_id),
            )
            for previous, current in zip(ordered, ordered[1:]):
                if previous.end_minute > current.start_minute:
                    add(
                        "MLCC-SV012",
                        resource_id,
                        f"Tasks {previous.task_id} and {current.task_id} overlap.",
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
        batches = {item.id: item for item in instance.batches}
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
