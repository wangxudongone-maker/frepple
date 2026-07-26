from django.db import connection
from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from freppledb.common.models import User
from freppledb.mlcc.demo import (
    DEMO_ORIGIN,
    INVALID_SOURCE,
    VALID_SOURCE,
    SolverDemoLoader,
)
from freppledb.mlcc.models import (
    MlccPrecheckRun,
    MlccScheduleResult,
    MlccScheduleRun,
)
from freppledb.mlcc.solver.api import (
    MlccPlanningInstanceAPI,
    MlccPrecheckAPI,
    MlccPrecheckResultAPI,
    MlccSolveAPI,
)


class SolverAPITest(TestCase):
    @classmethod
    def setUpTestData(cls):
        SolverDemoLoader().load_valid(100)
        if connection.vendor == "sqlite":
            user = User(
                id=9101,
                username="mlccsolveradmin",
                email="solver@example.com",
                is_superuser=True,
                is_active=False,
                databases=None,
            )
            user.set_password("admin")
            user._state.db = "default"
            user.save(force_insert=True)
            User.objects.filter(pk=user.pk).update(
                is_active=True, is_superuser=True, is_staff=True
            )
            with connection.cursor() as cursor:
                cursor.execute(
                    "update common_user set databases = %s where id = %s",
                    ["default", user.pk],
                )
        else:
            User.objects.create_superuser(
                "mlccsolveradmin", "solver@example.com", "admin"
            )

    def setUp(self):
        self.factory = APIRequestFactory()
        self.user = User.objects.get(username="mlccsolveradmin")
        self.payload = {
            "start": DEMO_ORIGIN.isoformat(),
            "horizon_days": 14,
            "freeze_hours": 48,
            "source": VALID_SOURCE,
        }

    def request(self, method, path, data=None, authenticated=True):
        request = getattr(self.factory, method)(path, data=data, format="json")
        request.database = "default"
        request.prefix = ""
        if authenticated:
            force_authenticate(request, user=self.user)
        return request

    def test_instance_api_requires_permission(self):
        request = self.request(
            "post",
            "/api/mlcc/planning-instance/",
            data=self.payload,
            authenticated=False,
        )
        response = MlccPlanningInstanceAPI.as_view()(request)
        self.assertIn(response.status_code, (401, 403))

    def test_instance_api_returns_pure_schema(self):
        request = self.request(
            "post", "/api/mlcc/planning-instance/", data=self.payload
        )
        response = MlccPlanningInstanceAPI.as_view()(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["instance"]["schema_version"], "mlcc-planning-instance/v1"
        )
        self.assertEqual(response.data["precheck"]["BLOCKER"], 0)
        self.assertEqual(len(response.data["instance"]["batches"]), 100)

    def test_precheck_api_persists_and_filters_results(self):
        request = self.request("post", "/api/mlcc/precheck/", data=self.payload)
        response = MlccPrecheckAPI.as_view()(request)
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data["can_start_solver"])
        run_id = response.data["run_id"]
        self.assertTrue(MlccPrecheckRun.objects.filter(pk=run_id).exists())

        request = self.request("get", f"/api/mlcc/precheck/{run_id}/?severity=BLOCKER")
        response = MlccPrecheckResultAPI.as_view()(request, pk=run_id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "passed")
        self.assertEqual(response.data["issues"], [])

    def test_invalid_precheck_filters_by_public_code_and_links_source_data(self):
        SolverDemoLoader().load_invalid()
        request = self.request(
            "post",
            "/api/mlcc/precheck/",
            data={**self.payload, "source": INVALID_SOURCE},
        )
        response = MlccPrecheckAPI.as_view()(request)
        self.assertEqual(response.status_code, 201)
        self.assertFalse(response.data["can_start_solver"])
        run_id = response.data["run_id"]

        request = self.request(
            "get", f"/api/mlcc/precheck/{run_id}/?code=MLCC-P001"
        )
        response = MlccPrecheckResultAPI.as_view()(request, pk=run_id)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["issues"])
        self.assertTrue(
            all(item["code"] == "MLCC-P001" for item in response.data["issues"])
        )
        self.assertTrue(
            all(item["object_url"] for item in response.data["issues"])
        )

    def test_invalid_api_options_return_400(self):
        request = self.request(
            "post",
            "/api/mlcc/precheck/",
            data={**self.payload, "horizon_days": 0},
        )
        response = MlccPrecheckAPI.as_view()(request)
        self.assertEqual(response.status_code, 400)

    def test_solve_api_requires_permission(self):
        request = self.request(
            "post",
            "/api/mlcc/solve/",
            data={**self.payload, "persist": False},
            authenticated=False,
        )
        response = MlccSolveAPI.as_view()(request)
        self.assertIn(response.status_code, (401, 403))

    def test_solve_api_returns_valid_preview_without_overwriting_plan(self):
        request = self.request(
            "post",
            "/api/mlcc/solve/",
            data={
                **self.payload,
                "horizon_days": 45,
                "max_time_seconds": 30,
                "workers": 1,
                "persist": True,
            },
        )
        response = MlccSolveAPI.as_view()(request)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertIn(response.data["status"], ("FEASIBLE", "OPTIMAL"))
        self.assertEqual(response.data["hard_constraint_violations"], 0)
        self.assertEqual(response.data["solution"]["solver_version"], "9.10.4067")
        self.assertEqual(len(response.data["solution"]["assignments"]), 500)
        self.assertTrue(
            MlccScheduleRun.objects.filter(
                pk=response.data["preview_run_id"],
                status="complete",
            ).exists()
        )
        self.assertEqual(
            MlccScheduleResult.objects.filter(
                run_id=response.data["preview_run_id"],
                status="proposed",
                details__preview_only=True,
            ).count(),
            500,
        )

    def test_solve_api_does_not_start_with_blockers(self):
        SolverDemoLoader().load_invalid()
        request = self.request(
            "post",
            "/api/mlcc/solve/",
            data={
                **self.payload,
                "source": INVALID_SOURCE,
                "persist": False,
            },
        )
        response = MlccSolveAPI.as_view()(request)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["status"], "BLOCKED")
        self.assertFalse(
            MlccScheduleRun.objects.filter(source=INVALID_SOURCE).exists()
        )

        request = self.request(
            "post",
            "/api/mlcc/precheck/",
            data={**self.payload, "factory_timezone": "Invalid/Timezone"},
        )
        response = MlccPrecheckAPI.as_view()(request)
        self.assertEqual(response.status_code, 400)
