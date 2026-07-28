from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import DEFAULT_DB_ALIAS

from freppledb.mlcc.solver.cpsat import PrecheckBlockedError, solve
from freppledb.mlcc.solver.serializer import load_planning_instance
from freppledb.mlcc.solver.service import build_and_validate
from freppledb.mlcc.solver.solution import (
    SolverParameters,
    scheduling_solution_json,
)
from freppledb.mlcc.solver.solution_validator import SchedulingSolutionValidator
from freppledb.mlcc.solver.solve_service import persist_preview_solution


class Command(BaseCommand):
    help = "Create an MLCC CP-SAT furnace-batching schedule preview"

    def add_arguments(self, parser):
        parser.add_argument("--database", default=DEFAULT_DB_ALIAS)
        parser.add_argument("--input")
        parser.add_argument("--output", required=True)
        parser.add_argument("--horizon-days", type=int, default=14)
        parser.add_argument("--freeze-hours", type=int, default=48)
        parser.add_argument("--start")
        parser.add_argument("--factory-timezone")
        parser.add_argument("--source")
        parser.add_argument("--max-time-seconds", type=float, default=60.0)
        parser.add_argument("--workers", type=int, default=1)
        parser.add_argument("--random-seed", type=int, default=0)
        parser.add_argument("--log-search-progress", action="store_true")
        parser.add_argument("--persist-preview", action="store_true")
        parser.add_argument("--compact", action="store_true")

    def handle(self, *args, **options):
        if options["max_time_seconds"] <= 0:
            raise CommandError("--max-time-seconds must be greater than zero")
        if options["workers"] <= 0:
            raise CommandError("--workers must be greater than zero")
        if options["input"]:
            try:
                instance = load_planning_instance(options["input"])
            except (OSError, TypeError, ValueError) as exc:
                raise CommandError(str(exc)) from exc
        else:
            instance, report, _ = build_and_validate(
                database=options["database"],
                horizon_start=options["start"],
                horizon_days=options["horizon_days"],
                freeze_hours=options["freeze_hours"],
                factory_timezone=options["factory_timezone"],
                source=options["source"],
            )
            if report.blocker_count:
                raise CommandError(
                    f"发现 {report.blocker_count} 个 BLOCKER；未启动 CP-SAT。"
                )

        parameters = SolverParameters(
            max_time_seconds=options["max_time_seconds"],
            num_search_workers=options["workers"],
            random_seed=options["random_seed"],
            log_search_progress=options["log_search_progress"],
        )
        try:
            solution = solve(instance, parameters)
        except PrecheckBlockedError as exc:
            raise CommandError(str(exc)) from exc

        validation = SchedulingSolutionValidator().validate(instance, solution)
        if solution.status not in ("FEASIBLE", "OPTIMAL"):
            raise CommandError(f"CP-SAT returned {solution.status}: {solution.message}")
        if not validation.valid:
            raise CommandError(
                f"Solution validator found {validation.violation_count} violation(s)"
            )

        output = Path(options["output"]).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            scheduling_solution_json(
                solution,
                pretty=not options["compact"],
            ),
            encoding="utf-8",
            newline="\n",
        )
        run = None
        if options["persist_preview"]:
            run = persist_preview_solution(
                instance,
                solution,
                database=options["database"],
                source=options["source"],
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"MLCC CP-SAT preview written to {output}; "
                f"status={solution.status}, tasks={solution.scheduled_task_count}, "
                f"furnace_loads={len(solution.furnace_loads)}, "
                f"load_delta={solution.metric_deltas.get('furnace_load_count', 0)}, "
                f"violations={validation.violation_count}, "
                f"duration={solution.wall_time_seconds:.3f}s"
                + (f", preview={run.name}" if run else "")
            )
        )
