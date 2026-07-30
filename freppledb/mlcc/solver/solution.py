"""Solver-neutral schedule solution contract and deterministic JSON output."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from .serializer import to_primitive

SOLUTION_SCHEMA_VERSION = "mlcc-schedule-solution/v2"
SOLUTION_MODES = (
    "phase3b_multi_batch",
    "phase3a_fallback",
    "phase3c_transition",
)


@dataclass(frozen=True)
class SolverParameters:
    max_time_seconds: float = 60.0
    num_search_workers: int = 1
    random_seed: int = 0
    log_search_progress: bool = False
    furnace_mode: str = "multi_batch_loads"


@dataclass(frozen=True)
class TaskAssignment:
    task_id: str
    batch_id: str
    stage: str
    resource_id: str
    start_minute: int
    end_minute: int
    frozen: bool
    furnace_load_id: str | None = None


@dataclass(frozen=True)
class OrderSchedule:
    order_id: str
    completion_minute: int
    due_minute: int | None
    tardiness_minutes: int
    priority: int
    priority_weight: int
    weighted_tardiness: int


@dataclass(frozen=True)
class ObjectiveStage:
    name: str
    status: str
    value: int | None
    best_bound: float | None
    wall_time_seconds: float


@dataclass(frozen=True)
class FurnaceLoadAssignment:
    load_id: str
    operation_type: str
    equipment_id: str
    recipe_id: str | None
    recipe_version: str | None
    furnace_program_key: str
    start_minute: int
    end_minute: int
    capacity: int
    loaded_quantity: int
    load_unit: str
    utilization: Decimal
    member_batch_ids: tuple[str, ...]
    member_task_ids: tuple[str, ...]
    compatibility_evidence: dict[str, tuple[str, ...]]
    conversion_evidence: dict[str, dict[str, Any]]
    frozen: bool
    status: str = "proposed"
    constraint_summary: dict[str, Any] = field(default_factory=dict)
    furnace_program_id: str | None = None
    furnace_program_version: str | None = None
    member_recipe_ids: tuple[str, ...] = ()
    predecessor_load_id: str | None = None
    successor_load_id: str | None = None
    setup_before_minutes: int = 0


@dataclass(frozen=True)
class FurnaceTransitionAssignment:
    transition_id: str
    equipment_id: str
    predecessor_load_id: str | None
    initial_state_id: str | None
    successor_load_id: str
    from_state_key: str
    to_program_key: str
    rule_id: str
    rule_scope_level: str
    transition_type: str
    start_minute: int
    end_minute: int
    duration_minutes: int
    frozen: bool
    status: str = "proposed"
    resolution_evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SchedulingSolution:
    status: str
    input_fingerprint: str
    solver_name: str
    solver_version: str
    parameters: SolverParameters
    assignments: tuple[TaskAssignment, ...] = ()
    furnace_loads: tuple[FurnaceLoadAssignment, ...] = ()
    furnace_transitions: tuple[FurnaceTransitionAssignment, ...] = ()
    orders: tuple[OrderSchedule, ...] = ()
    objective_stages: tuple[ObjectiveStage, ...] = ()
    objective_values: dict[str, int] = field(default_factory=dict)
    wall_time_seconds: float = 0.0
    optimality_gap: float | None = None
    message: str = ""
    solution_mode: str = "phase3b_multi_batch"
    fallback_reason: str | None = None
    last_successful_stage: str | None = None
    phase3a_baseline_metrics: dict[str, Any] = field(default_factory=dict)
    phase3b_metrics: dict[str, Any] = field(default_factory=dict)
    metric_deltas: dict[str, Any] = field(default_factory=dict)
    phase3b_reference_metrics: dict[str, Any] = field(default_factory=dict)
    phase3c_metrics: dict[str, Any] = field(default_factory=dict)
    transition_constraint_cost: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SOLUTION_SCHEMA_VERSION

    @property
    def scheduled_task_count(self):
        return len(self.assignments)


def scheduling_solution_json(solution, pretty=False):
    options: dict[str, Any] = {"ensure_ascii": False, "sort_keys": True}
    if pretty:
        options["indent"] = 2
    else:
        options["separators"] = (",", ":")
    return json.dumps(to_primitive(solution), **options) + "\n"


def scheduling_solution_fingerprint(solution):
    payload = scheduling_solution_json(solution, pretty=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
