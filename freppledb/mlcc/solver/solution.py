"""Solver-neutral schedule solution contract and deterministic JSON output."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from .serializer import to_primitive

SOLUTION_SCHEMA_VERSION = "mlcc-schedule-solution/v1"
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
    recipe_id: str
    recipe_version: str
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


@dataclass(frozen=True)
class SchedulingSolution:
    status: str
    input_fingerprint: str
    solver_name: str
    solver_version: str
    parameters: SolverParameters
    assignments: tuple[TaskAssignment, ...] = ()
    furnace_loads: tuple[FurnaceLoadAssignment, ...] = ()
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
