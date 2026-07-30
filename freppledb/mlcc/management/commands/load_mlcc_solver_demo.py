import json

from django.core.management.base import BaseCommand, CommandError
from django.db import DEFAULT_DB_ALIAS

from freppledb.common.middleware import _thread_locals
from freppledb.mlcc.demo import SolverDemoLoader


class Command(BaseCommand):
    help = "Load deterministic MLCC solver input demonstration data"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dataset",
            choices=(
                "valid_demo",
                "invalid_demo",
                "same_program_demo",
                "transition_demo",
                "both",
            ),
            default="both",
        )
        parser.add_argument("--batches", type=int, default=100)
        parser.add_argument("--database", default=DEFAULT_DB_ALIAS)

    def handle(self, *args, **options):
        database = options["database"]
        previous_database = getattr(_thread_locals, "database", None)
        setattr(_thread_locals, "database", database)
        try:
            loader = SolverDemoLoader(database)
            result = []
            if options["dataset"] in ("valid_demo", "both"):
                try:
                    result.append(loader.load_valid(options["batches"]))
                except ValueError as exc:
                    raise CommandError(str(exc)) from exc
            if options["dataset"] in ("invalid_demo", "both"):
                result.append(loader.load_invalid())
            if options["dataset"] == "same_program_demo":
                try:
                    result.append(loader.load_same_program(options["batches"]))
                except ValueError as exc:
                    raise CommandError(str(exc)) from exc
            if options["dataset"] == "transition_demo":
                try:
                    result.append(loader.load_transition(options["batches"]))
                except ValueError as exc:
                    raise CommandError(str(exc)) from exc
            self.stdout.write(
                self.style.SUCCESS(
                    json.dumps(result, ensure_ascii=False, sort_keys=True)
                )
            )
        finally:
            if previous_database is None:
                try:
                    delattr(_thread_locals, "database")
                except AttributeError:
                    pass
            else:
                setattr(_thread_locals, "database", previous_database)
