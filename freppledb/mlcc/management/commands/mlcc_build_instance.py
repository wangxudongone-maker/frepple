from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import DEFAULT_DB_ALIAS

from freppledb.mlcc.solver.serializer import planning_instance_json
from freppledb.mlcc.solver.service import build_and_validate, persist_precheck


class Command(BaseCommand):
    help = "Build deterministic, solver-neutral MLCC planning input"

    def add_arguments(self, parser):
        parser.add_argument("--database", default=DEFAULT_DB_ALIAS)
        parser.add_argument("--horizon-days", type=int, default=14)
        parser.add_argument("--freeze-hours", type=int, default=48)
        parser.add_argument("--start")
        parser.add_argument("--factory-timezone")
        parser.add_argument("--source")
        parser.add_argument("--output", required=True)
        parser.add_argument("--compact", action="store_true")
        parser.add_argument("--allow-blockers", action="store_true")
        parser.add_argument("--no-persist", action="store_true")

    def handle(self, *args, **options):
        if options["horizon_days"] <= 0:
            raise CommandError("--horizon-days must be greater than zero")
        if options["freeze_hours"] < 0:
            raise CommandError("--freeze-hours cannot be negative")

        try:
            instance, report, duration_ms = build_and_validate(
                database=options["database"],
                horizon_start=options["start"],
                horizon_days=options["horizon_days"],
                freeze_hours=options["freeze_hours"],
                factory_timezone=options["factory_timezone"],
                source=options["source"],
            )
        except (TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        run = None
        if not options["no_persist"]:
            run = persist_precheck(
                instance,
                report,
                duration_ms,
                database=options["database"],
                source=options["source"],
                parameters={
                    "horizon_days": options["horizon_days"],
                    "freeze_hours": options["freeze_hours"],
                    "source": options["source"],
                },
            )
        if report.blocker_count and not options["allow_blockers"]:
            reference = f"，预检记录 {run.reference}" if run else ""
            raise CommandError(
                f"发现 {report.blocker_count} 个 BLOCKER{reference}；未生成求解器输入。"
            )

        output = Path(options["output"]).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            planning_instance_json(instance, pretty=not options["compact"]),
            encoding="utf-8",
            newline="\n",
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"MLCC planning instance written to {output}; "
                f"orders={instance.counts['orders']}, "
                f"batches={instance.counts['batches']}, "
                f"tasks={instance.counts['tasks']}, "
                f"equipment={instance.counts['equipment']}, "
                f"BLOCKER={report.blocker_count}, "
                f"WARNING={report.warning_count}, duration_ms={duration_ms}."
            )
        )
