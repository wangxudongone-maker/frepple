"""Django adapter for preview-only persistence of pure solver output."""

from dataclasses import asdict
from datetime import datetime, timedelta
import hashlib
import json

from django.conf import settings
from django.db import DEFAULT_DB_ALIAS, transaction
from django.utils import timezone

from freppledb.input.models import ManufacturingOrder, Resource
from freppledb.mlcc.models import (
    MlccFurnaceLoad,
    MlccFurnaceLoadItem,
    MlccFurnaceProgram,
    MlccFurnaceTransition,
    MlccFurnaceTransitionRule,
    MlccRecipe,
    MlccScheduleResult,
    MlccScheduleRun,
)

from .service import selected_database
from .extractor import stable_id, timedelta_minutes
from .serializer import to_primitive
from .solution_validator import SchedulingSolutionValidator
from .transition_rules import stable_transition_rule_id


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
    resource_ids = [item.resource_id.split(":", 1)[-1] for item in solution.assignments]
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
    business_payload = "|".join(
        f"{item.task_id}:{item.resource_id}:{item.start_minute}:{item.end_minute}:"
        f"{item.furnace_load_id or ''}"
        for item in sorted(solution.assignments, key=lambda item: item.task_id)
    )
    business_payload += "|" + json.dumps(
        to_primitive(solution.furnace_transitions),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    business_hash = hashlib.sha256(business_payload.encode("utf-8")).hexdigest()
    phase = "C" if solution.solution_mode == "phase3c_transition" else "B"
    name = (
        f"MLCC-CP-SAT-{phase}-"
        f"{solution.input_fingerprint[:12]}-{business_hash[:12]}"
    )
    steps = {item.id: item for item in instance.steps}
    ordered_assignments = sorted(
        solution.assignments,
        key=lambda item: (item.start_minute, item.task_id),
    )

    with selected_database(database), transaction.atomic(using=database):
        existing = MlccScheduleRun.objects.using(database).filter(name=name).first()
        if existing:
            return existing
        run = MlccScheduleRun(
            name=name,
            status="complete",
            horizon_start=_database_datetime(origin),
            horizon_end=_database_datetime(horizon_end),
            requested_at=_database_datetime(now),
            started_at=_database_datetime(now),
            finished_at=_database_datetime(now),
            parameters=to_primitive(
                {
                    "preview_only": True,
                    "input_fingerprint": solution.input_fingerprint,
                    "solver_name": solution.solver_name,
                    "solver_version": solution.solver_version,
                    "solver_parameters": asdict(solution.parameters),
                    "solution_mode": solution.solution_mode,
                    "fallback_reason": solution.fallback_reason,
                    "last_successful_stage": solution.last_successful_stage,
                    "objective_values": solution.objective_values,
                    "optimality_gap": solution.optimality_gap,
                    "phase3a_baseline_metrics": solution.phase3a_baseline_metrics,
                    "phase3b_metrics": solution.phase3b_metrics,
                    "phase3b_reference_metrics": solution.phase3b_reference_metrics,
                    "phase3c_metrics": solution.phase3c_metrics,
                    "transition_constraint_cost": solution.transition_constraint_cost,
                    "metric_deltas": solution.metric_deltas,
                }
            ),
            message=(
                f"CP-SAT {solution.solution_mode} preview; "
                "no production plan was updated."
            ),
            source=source,
        )
        run.save(using=database)
        schema_recipes = {item.id: item for item in instance.recipes}
        database_recipes = {
            (item.name, item.version): item
            for item in MlccRecipe.objects.using(database).filter(
                name__in={
                    schema_recipes[item.recipe_id].name
                    for item in solution.furnace_loads
                    if item.recipe_id
                }
            )
        }
        database_programs = MlccFurnaceProgram.objects.using(database).in_bulk(
            [
                item.furnace_program_id.split(":", 1)[-1]
                for item in solution.furnace_loads
                if item.furnace_program_id
            ]
        )
        persisted_loads = {}
        for sequence, load in enumerate(
            sorted(solution.furnace_loads, key=lambda item: item.load_id), 1
        ):
            if load.frozen:
                reference = load.load_id.split(":", 1)[-1]
                persisted = MlccFurnaceLoad.objects.using(database).get(
                    reference=reference
                )
            else:
                schema_recipe = (
                    schema_recipes[load.recipe_id] if load.recipe_id else None
                )
                program_pk = (
                    load.furnace_program_id.split(":", 1)[-1]
                    if load.furnace_program_id
                    else None
                )
                persisted = MlccFurnaceLoad(
                    reference=f"{name}-F{sequence:05d}",
                    run=run,
                    resource_id=load.equipment_id.split(":", 1)[-1],
                    recipe=(
                        database_recipes[(schema_recipe.name, schema_recipe.version)]
                        if schema_recipe
                        else None
                    ),
                    furnace_program=(
                        database_programs[program_pk] if program_pk else None
                    ),
                    operation_type=load.operation_type,
                    furnace_program_key=load.furnace_program_key,
                    planned_start=_database_datetime(
                        origin + timedelta(minutes=load.start_minute)
                    ),
                    planned_end=_database_datetime(
                        origin + timedelta(minutes=load.end_minute)
                    ),
                    status="proposed",
                    capacity=load.capacity,
                    loaded_quantity=load.loaded_quantity,
                    load_unit=load.load_unit,
                    frozen=False,
                    details={
                        "preview_only": True,
                        "solver_load_id": load.load_id,
                        "utilization": str(load.utilization),
                        "compatibility_evidence": load.compatibility_evidence,
                        "member_recipe_ids": load.member_recipe_ids,
                        "furnace_program_id": load.furnace_program_id,
                        "furnace_program_version": load.furnace_program_version,
                        "predecessor_load_id": load.predecessor_load_id,
                        "successor_load_id": load.successor_load_id,
                        "setup_before_minutes": load.setup_before_minutes,
                        "constraint_summary": load.constraint_summary,
                    },
                    source=source,
                )
                persisted.save(using=database)
                MlccFurnaceLoadItem.objects.using(database).bulk_create(
                    [
                        MlccFurnaceLoadItem(
                            furnace_load=persisted,
                            manufacturing_order_id=task_id.split(":", 1)[-1],
                            batch_code=steps[task_id].batch_id.split(":", 1)[-1],
                            quantity=load.conversion_evidence[steps[task_id].batch_id][
                                "load_quantity"
                            ],
                            load_unit=load.load_unit,
                            conversion_trace=to_primitive(
                                load.conversion_evidence[steps[task_id].batch_id]
                            ),
                            sequence=item_sequence,
                            source=source,
                        )
                        for item_sequence, task_id in enumerate(load.member_task_ids, 1)
                    ],
                    batch_size=500,
                )
            persisted_loads[load.load_id] = persisted

        rule_queryset = MlccFurnaceTransitionRule.objects.using(
            database
        ).select_related("resource", "to_program")
        if source is not None:
            rule_queryset = rule_queryset.filter(source=source)
        database_transition_rules = {}
        for rule in rule_queryset:
            business_id = stable_transition_rule_id(
                (stable_id("resource", rule.resource_id) if rule.resource_id else None),
                rule.equipment_group,
                rule.process_stage,
                rule.from_state_key,
                stable_id("furnace_program", rule.to_program_id),
                rule.transition_type,
                timedelta_minutes(rule.duration) or 0,
                rule.setup_cost,
                rule.allowed,
                rule.enabled,
                rule.priority,
                rule.effective_date.isoformat(),
                rule.expiry_date.isoformat() if rule.expiry_date else None,
            )
            database_transition_rules[business_id] = rule
        for transition_assignment in sorted(
            solution.furnace_transitions,
            key=lambda item: (
                item.equipment_id,
                item.start_minute,
                item.transition_id,
            ),
        ):
            persisted_transition = MlccFurnaceTransition(
                run=run,
                resource_id=transition_assignment.equipment_id.split(":", 1)[-1],
                predecessor_load=(
                    persisted_loads[transition_assignment.predecessor_load_id]
                    if transition_assignment.predecessor_load_id
                    else None
                ),
                successor_load=persisted_loads[transition_assignment.successor_load_id],
                transition_rule=database_transition_rules[
                    transition_assignment.rule_id
                ],
                transition_type=transition_assignment.transition_type,
                planned_start=_database_datetime(
                    origin + timedelta(minutes=transition_assignment.start_minute)
                ),
                planned_end=_database_datetime(
                    origin + timedelta(minutes=transition_assignment.end_minute)
                ),
                status="proposed",
                details={
                    "preview_only": True,
                    "solver_transition_id": transition_assignment.transition_id,
                    "initial_state_id": transition_assignment.initial_state_id,
                    "from_state_key": transition_assignment.from_state_key,
                    "to_program_key": transition_assignment.to_program_key,
                    "rule_scope_level": (transition_assignment.rule_scope_level),
                    "frozen": transition_assignment.frozen,
                    "resolution_evidence": (transition_assignment.resolution_evidence),
                },
                source=source,
            )
            persisted_transition.save(using=database)

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
                    furnace_load=persisted_loads.get(assignment.furnace_load_id),
                    sequence=sequence,
                    details={
                        "preview_only": True,
                        "stage": assignment.stage,
                        "frozen": assignment.frozen,
                        "input_fingerprint": solution.input_fingerprint,
                        "furnace_load_id": assignment.furnace_load_id,
                    },
                    source=source,
                )
                for sequence, assignment in enumerate(ordered_assignments, 1)
            ],
            batch_size=500,
        )
    return run
