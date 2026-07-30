from django.db import DEFAULT_DB_ALIAS
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from freppledb.common.api.views import frepplePermissionClass
from freppledb.mlcc.models import MlccPrecheckRun, MlccScheduleRun

from .cpsat import solve as solve_phase3b
from .phase3c import PrecheckBlockedError
from .phase3c import solve as solve_phase3c
from .serializer import (
    planning_instance_fingerprint,
    to_primitive,
)
from .service import build_and_validate, persist_precheck, report_payload
from .solution import SolverParameters
from .solution_validator import SchedulingSolutionValidator
from .solve_service import persist_preview_solution


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


def _boolean(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in ("1", "true", "yes", "on"):
        return True
    if normalized in ("0", "false", "no", "off"):
        return False
    raise ValueError(f"Invalid boolean value: {value!r}")


class MlccSolveAPI(APIView):
    permission_classes = (frepplePermissionClass,)
    queryset = MlccScheduleRun.objects.all()

    def post(self, request):
        try:
            options = request_options(request)
            max_time_seconds = float(request.data.get("max_time_seconds", 60))
            workers = int(request.data.get("workers", 1))
            random_seed = int(request.data.get("random_seed", 0))
            persist = _boolean(request.data.get("persist"), default=True)
            solver_phase = request.data.get("solver_phase", "phase3c")
            if solver_phase not in ("phase3b", "phase3c"):
                raise ValueError("solver_phase must be phase3b or phase3c")
            if max_time_seconds <= 0 or workers <= 0:
                raise ValueError(
                    "max_time_seconds and workers must be greater than zero"
                )
            instance, report, duration_ms = build_and_validate(**options)
        except (TypeError, ValueError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        if report.blocker_count:
            return Response(
                {
                    "status": "BLOCKED",
                    "detail": "预检存在 BLOCKER，未启动 CP-SAT。",
                    "precheck": report_payload(report),
                },
                status=status.HTTP_409_CONFLICT,
            )

        parameters = SolverParameters(
            max_time_seconds=max_time_seconds,
            num_search_workers=workers,
            random_seed=random_seed,
            log_search_progress=False,
        )
        try:
            solution = (
                solve_phase3c(instance, parameters)
                if solver_phase == "phase3c"
                else solve_phase3b(instance, parameters)
            )
        except PrecheckBlockedError as exc:
            return Response(
                {
                    "status": "BLOCKED",
                    "detail": str(exc),
                    "precheck": report_payload(exc.report),
                },
                status=status.HTTP_409_CONFLICT,
            )
        validation = SchedulingSolutionValidator().validate(instance, solution)
        if solution.status not in ("FEASIBLE", "OPTIMAL"):
            return Response(
                {
                    "status": solution.status,
                    "detail": solution.message,
                    "solution": to_primitive(solution),
                },
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        if not validation.valid:
            return Response(
                {
                    "status": "INVALID_SOLUTION",
                    "violations": [
                        to_primitive(item) for item in validation.violations
                    ],
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        run = (
            persist_preview_solution(
                instance,
                solution,
                database=options["database"],
                source=options["source"],
            )
            if persist
            else None
        )
        return Response(
            {
                "status": solution.status,
                "preview_run_id": run.pk if run else None,
                "preview_run": run.name if run else None,
                "precheck_duration_ms": duration_ms,
                "hard_constraint_violations": validation.violation_count,
                "solution": to_primitive(solution),
            },
            status=status.HTTP_201_CREATED if run else status.HTTP_200_OK,
        )
