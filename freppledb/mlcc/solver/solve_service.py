"""Django adapter for preview-only persistence of pure solver output."""

from dataclasses import asdict
from datetime import datetime, timedelta

from django.conf import settings
from django.db import DEFAULT_DB_ALIAS, transaction
from django.utils import timezone

from freppledb.input.models import ManufacturingOrder, Resource
from freppledb.mlcc.models import MlccScheduleResult, MlccScheduleRun

from .service import selected_database
from .solution_validator import SchedulingSolutionValidator


def _database_datetime(value):
    if settings.USE_TZ:
        return value
    return value.replace(tzinfo=None)


def persist_preview_solution(
    instance,
    solution,
    database=DEFAULT_DB_ALIAS,
    source=None,
):
    """Create a new preview version without changing any frePPLe plan records."""

    if solution.status not in ("FEASIBLE", "OPTIMAL"):
        raise ValueError("Only a feasible solution can be persisted as preview")
    validation = SchedulingSolutionValidator().validate(instance, solution)
    if not validation.valid:
        raise ValueError(
            f"Solution has {validation.violation_count} hard-constraint violation(s)"
        )

    task_ids = [item.task_id.split(":", 1)[-1] for item in solution.assignments]
    resource_ids = [
        item.resource_id.split(":", 1)[-1] for item in solution.assignments
    ]
    operations = ManufacturingOrder.objects.using(database).in_bulk(task_ids)
    resources = Resource.objects.using(database).in_bulk(resource_ids)
    if set(task_ids) != set(operations):
        missing = sorted(set(task_ids) - set(operations))
        raise ValueError(f"Preview tasks are missing from database: {missing}")
    if set(resource_ids) != set(resources):
        missing = sorted(set(resource_ids) - set(resources))
        raise ValueError(f"Preview resources are missing from database: {missing}")

    origin = datetime.fromisoformat(instance.window.origin)
    horizon_end = origin + timedelta(minutes=instance.window.horizon_minutes)
    now = timezone.now()
    name = (
        f"MLCC-CP-SAT-{now.strftime('%Y%m%d%H%M%S%f')}-"
        f"{solution.input_fingerprint[:8]}"
    )
    steps = {item.id: item for item in instance.steps}
    ordered_assignments = sorted(
        solution.assignments,
        key=lambda item: (item.start_minute, item.task_id),
    )

    with selected_database(database), transaction.atomic(using=database):
        run = MlccScheduleRun(
            name=name,
            status="complete",
            horizon_start=_database_datetime(origin),
            horizon_end=_database_datetime(horizon_end),
            requested_at=_database_datetime(now),
            started_at=_database_datetime(now),
            finished_at=_database_datetime(now),
            parameters={
                "preview_only": True,
                "input_fingerprint": solution.input_fingerprint,
                "solver_name": solution.solver_name,
                "solver_version": solution.solver_version,
                "solver_parameters": asdict(solution.parameters),
                "objective_values": solution.objective_values,
                "optimality_gap": solution.optimality_gap,
            },
            message="CP-SAT baseline preview; no production plan was updated.",
            source=source,
        )
        run.save(using=database)
        MlccScheduleResult.objects.using(database).bulk_create(
            [
                MlccScheduleResult(
                    run=run,
                    manufacturing_order_id=assignment.task_id.split(":", 1)[-1],
                    resource_id=assignment.resource_id.split(":", 1)[-1],
                    batch_code=assignment.batch_id.split(":", 1)[-1],
                    planned_start=_database_datetime(
                        origin + timedelta(minutes=assignment.start_minute)
                    ),
                    planned_end=_database_datetime(
                        origin + timedelta(minutes=assignment.end_minute)
                    ),
                    quantity=steps[assignment.task_id].quantity,
                    status="proposed",
                    sequence=sequence,
                    details={
                        "preview_only": True,
                        "stage": assignment.stage,
                        "frozen": assignment.frozen,
                        "input_fingerprint": solution.input_fingerprint,
                    },
                    source=source,
                )
                for sequence, assignment in enumerate(ordered_assignments, 1)
            ],
            batch_size=500,
        )
    return run
