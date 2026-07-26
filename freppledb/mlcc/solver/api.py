from django.db import DEFAULT_DB_ALIAS
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from freppledb.common.api.views import frepplePermissionClass
from freppledb.mlcc.models import MlccPrecheckRun

from .serializer import (
    planning_instance_fingerprint,
    to_primitive,
)
from .service import build_and_validate, persist_precheck, report_payload


def request_options(request):
    values = request.data if request.method == "POST" else request.query_params
    try:
        horizon_days = int(values.get("horizon_days", 14))
        freeze_hours = int(values.get("freeze_hours", 48))
    except (TypeError, ValueError) as exc:
        raise ValueError("horizon_days and freeze_hours must be integers") from exc
    if horizon_days <= 0 or freeze_hours < 0:
        raise ValueError("horizon_days must be positive and freeze_hours non-negative")
    return {
        "database": getattr(request, "database", None) or DEFAULT_DB_ALIAS,
        "horizon_start": values.get("start") or None,
        "horizon_days": horizon_days,
        "freeze_hours": freeze_hours,
        "factory_timezone": values.get("factory_timezone") or None,
        "source": values.get("source") or None,
    }


class MlccPlanningInstanceAPI(APIView):
    permission_classes = (frepplePermissionClass,)
    queryset = MlccPrecheckRun.objects.all()

    def post(self, request):
        try:
            options = request_options(request)
            instance, report, duration_ms = build_and_validate(**options)
        except (TypeError, ValueError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {
                "fingerprint": planning_instance_fingerprint(instance),
                "duration_ms": duration_ms,
                "precheck": report.summary,
                "instance": to_primitive(instance),
            }
        )


class MlccPrecheckAPI(APIView):
    permission_classes = (frepplePermissionClass,)
    queryset = MlccPrecheckRun.objects.all()

    def post(self, request):
        try:
            options = request_options(request)
            instance, report, duration_ms = build_and_validate(**options)
        except (TypeError, ValueError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
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
        return Response(
            {
                "run_id": run.pk,
                "reference": run.reference,
                "instance_hash": run.instance_hash,
                "counts": instance.counts,
                "duration_ms": duration_ms,
                **report_payload(report),
            },
            status=status.HTTP_201_CREATED,
        )


class MlccPrecheckResultAPI(APIView):
    permission_classes = (frepplePermissionClass,)
    queryset = MlccPrecheckRun.objects.all()

    def get(self, request, pk):
        database = getattr(request, "database", None) or DEFAULT_DB_ALIAS
        try:
            run = MlccPrecheckRun.objects.using(database).get(pk=pk)
        except MlccPrecheckRun.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        issues = run.issues.using(database).all()
        for field in ("severity", "code", "object_type", "object_id"):
            value = request.query_params.get(field)
            if value:
                issues = issues.filter(**{field: value})
        return Response(
            {
                "run_id": run.pk,
                "reference": run.reference,
                "status": run.status,
                "instance_hash": run.instance_hash,
                "counts": {
                    "orders": run.order_count,
                    "batches": run.batch_count,
                    "tasks": run.task_count,
                    "equipment": run.equipment_count,
                },
                "summary": {
                    "BLOCKER": run.blocker_count,
                    "WARNING": run.warning_count,
                    "INFO": run.info_count,
                    "can_start_solver": run.blocker_count == 0,
                },
                "issues": [
                    {
                        "code": item.code,
                        "severity": item.severity,
                        "object_type": item.object_type,
                        "object_id": item.object_id,
                        "reason": item.reason,
                        "suggestion": item.suggestion,
                        "source_field": item.source_field,
                        "object_url": item.object_url,
                    }
                    for item in issues.order_by("sequence")
                ],
            }
        )
