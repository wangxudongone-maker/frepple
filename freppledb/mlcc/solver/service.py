"""Application service coordinating extraction, validation and persistence."""

from contextlib import contextmanager
from datetime import datetime, timedelta
from time import perf_counter
from urllib.parse import quote_plus

from django.conf import settings
from django.db import DEFAULT_DB_ALIAS, transaction
from django.utils import timezone

from freppledb.common.middleware import _thread_locals
from freppledb.mlcc.models import MlccPrecheckIssue, MlccPrecheckRun

from .extractor import PlanningInstanceExtractor
from .serializer import planning_instance_fingerprint
from .validator import PlanningInstanceValidator


@contextmanager
def selected_database(database):
    previous = getattr(_thread_locals, "database", None)
    setattr(_thread_locals, "database", database)
    try:
        yield
    finally:
        if previous is None:
            try:
                delattr(_thread_locals, "database")
            except AttributeError:
                pass
        else:
            setattr(_thread_locals, "database", previous)


def build_and_validate(
    database=DEFAULT_DB_ALIAS,
    horizon_start=None,
    horizon_days=14,
    freeze_hours=48,
    factory_timezone=None,
    source=None,
):
    started = perf_counter()
    with selected_database(database):
        instance = PlanningInstanceExtractor(
            database=database,
            horizon_start=horizon_start,
            horizon_days=horizon_days,
            freeze_hours=freeze_hours,
            factory_timezone=factory_timezone,
            source=source,
        ).extract()
        report = PlanningInstanceValidator().validate(instance)
    duration_ms = max(0, int((perf_counter() - started) * 1000))
    return instance, report, duration_ms


def object_url(object_type, object_id, database=DEFAULT_DB_ALIAS):
    value = quote_plus(object_id.split(":", 1)[-1])
    prefix = "" if database == DEFAULT_DB_ALIAS else f"/{database}"
    routes = {
        "customer_order": f"{prefix}/data/input/demand/?name={value}",
        "task": f"{prefix}/data/input/manufacturingorder/?reference={value}",
        "resource": f"{prefix}/data/input/resource/?name={value}",
        "recipe": f"{prefix}/data/mlcc/mlccrecipe/",
        "compatibility_rule": f"{prefix}/data/mlcc/mlcccompatibilityrule/",
        "production_batch": (
            f"{prefix}/data/input/manufacturingorder/?mlcc_lot_number={value}"
        ),
    }
    return routes.get(object_type, "")


def persist_precheck(
    instance,
    report,
    duration_ms,
    database=DEFAULT_DB_ALIAS,
    source=None,
    parameters=None,
):
    origin = datetime.fromisoformat(instance.window.origin)
    horizon_end = origin + timedelta(minutes=instance.window.horizon_minutes)
    if not settings.USE_TZ:
        # frePPLe's default database contract stores factory-local timestamps.
        # The solver schema remains offset-aware; persistence follows Django's
        # configured DateTimeField semantics.
        origin = origin.replace(tzinfo=None)
        horizon_end = horizon_end.replace(tzinfo=None)
    fingerprint = planning_instance_fingerprint(instance)
    reference = (
        f"PRECHECK-{timezone.now().strftime('%Y%m%d%H%M%S%f')}-{fingerprint[:8]}"
    )
    counts = instance.counts
    with selected_database(database), transaction.atomic(using=database):
        run = MlccPrecheckRun(
            reference=reference,
            status="blocked" if report.blocker_count else "passed",
            horizon_start=origin,
            horizon_end=horizon_end,
            freeze_minutes=instance.window.freeze_minutes,
            factory_timezone=instance.window.timezone,
            instance_hash=fingerprint,
            order_count=counts["orders"],
            batch_count=counts["batches"],
            task_count=counts["tasks"],
            equipment_count=counts["equipment"],
            blocker_count=report.blocker_count,
            warning_count=report.warning_count,
            info_count=report.info_count,
            duration_ms=duration_ms,
            parameters=parameters or {},
            source=source,
        )
        run.save(using=database)
        MlccPrecheckIssue.objects.using(database).bulk_create(
            [
                MlccPrecheckIssue(
                    run=run,
                    sequence=sequence,
                    severity=item.severity,
                    code=item.code,
                    object_type=item.object_type,
                    object_id=item.object_id,
                    reason=item.reason,
                    suggestion=item.suggestion,
                    source_field=item.source_field,
                    object_url=object_url(item.object_type, item.object_id, database),
                    source=source,
                )
                for sequence, item in enumerate(report.issues, 1)
            ]
        )
    return run


def report_payload(report):
    return {
        **report.summary,
        "issues": [
            {
                "code": item.code,
                "severity": item.severity,
                "object_type": item.object_type,
                "object_id": item.object_id,
                "reason": item.reason,
                "suggestion": item.suggestion,
                "source_field": item.source_field,
            }
            for item in report.issues
        ],
    }
