"""Solver-neutral schedule solution contract and deterministic JSON output."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from .serializer import to_primitive

SOLUTION_SCHEMA_VERSION = "mlcc-schedule-solution/v1"


@dataclass(frozen=True)
class SolverParameters:
    max_time_seconds: float = 60.0
    num_search_workers: int = 1
    random_seed: int = 0
    log_search_progress: bool = False
    furnace_mode: str = "one_batch_per_run"


@dataclass(frozen=True)
class TaskAssignment:
    task_id: str
    batch_id: str
    stage: str
    resource_id: str
    start_minute: int
    end_minute: int
    frozen: bool


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
class SchedulingSolution:
    status: str
    input_fingerprint: str
    solver_name: str
    solver_version: str
    parameters: SolverParameters
    assignments: tuple[TaskAssignment, ...] = ()
    orders: tuple[OrderSchedule, ...] = ()
    objective_stages: tuple[ObjectiveStage, ...] = ()
    objective_values: dict[str, int] = field(default_factory=dict)
    wall_time_seconds: float = 0.0
    optimality_gap: float | None = None
    message: str = ""
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
