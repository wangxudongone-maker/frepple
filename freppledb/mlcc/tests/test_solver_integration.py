import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from freppledb.mlcc.demo import (
    DEMO_ORIGIN,
    INVALID_SOURCE,
    VALID_SOURCE,
    SolverDemoLoader,
)
from freppledb.mlcc.solver.serializer import (
    planning_instance_fingerprint,
    planning_instance_json,
)
from freppledb.mlcc.solver.cpsat import solve
from freppledb.mlcc.solver.service import build_and_validate
from freppledb.mlcc.solver.solution import SolverParameters
from freppledb.mlcc.solver.solution_validator import SchedulingSolutionValidator


class ValidSolverDemoIntegrationTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.metadata = SolverDemoLoader().load_valid(100)

    def test_extractor_counts_and_precheck(self):
        instance, report, duration_ms = build_and_validate(
            horizon_start=DEMO_ORIGIN,
            horizon_days=14,
            freeze_hours=48,
            source=VALID_SOURCE,
        )
        self.assertEqual(instance.counts["orders"], 100)
        self.assertEqual(instance.counts["batches"], 100)
        self.assertEqual(instance.counts["tasks"], 500)
        self.assertEqual(instance.counts["equipment"], 5)
        self.assertEqual(report.blocker_count, 0, report.issues)
        self.assertLess(duration_ms, 30000)
        self.assertIsInstance(instance.steps[0].candidate_resource_ids, tuple)

    def test_repeated_extraction_has_identical_business_json(self):
        first, _, _ = build_and_validate(horizon_start=DEMO_ORIGIN, source=VALID_SOURCE)
        second, _, _ = build_and_validate(
            horizon_start=DEMO_ORIGIN, source=VALID_SOURCE
        )
        first_json = planning_instance_json(first)
        self.assertEqual(first_json, planning_instance_json(second))
        self.assertEqual(
            planning_instance_fingerprint(first), planning_instance_fingerprint(second)
        )
        self.assertEqual(
            planning_instance_fingerprint(first),
            hashlib.sha256(first_json.encode("utf-8")).hexdigest(),
        )

    def test_valid_demo_can_be_loaded_twice_without_business_drift(self):
        loader = SolverDemoLoader()
        loader.load_valid(100)
        first, first_report, _ = build_and_validate(
            horizon_start=DEMO_ORIGIN, source=VALID_SOURCE
        )
        loader.load_valid(100)
        second, second_report, _ = build_and_validate(
            horizon_start=DEMO_ORIGIN, source=VALID_SOURCE
        )
        self.assertEqual(first_report.blocker_count, 0)
        self.assertEqual(second_report.blocker_count, 0)
        self.assertEqual(planning_instance_json(first), planning_instance_json(second))

    def test_management_command_writes_instance(self):
        with TemporaryDirectory() as directory:
            output = Path(directory) / "planning_instance.json"
            call_command(
                "mlcc_build_instance",
                horizon_days=14,
                freeze_hours=48,
                start=DEMO_ORIGIN.isoformat(),
                source=VALID_SOURCE,
                output=str(output),
                no_persist=True,
                verbosity=0,
            )
            self.assertTrue(output.exists())
            self.assertIn(
                '"schema_version": "mlcc-planning-instance/v2"',
                output.read_text(encoding="utf-8"),
            )

    def test_500_batch_performance_acceptance(self):
        SolverDemoLoader().load_valid(500)
        started = perf_counter()
        instance, report, _ = build_and_validate(
            horizon_start=DEMO_ORIGIN, source=VALID_SOURCE
        )
        elapsed = perf_counter() - started
        self.assertEqual(instance.counts["batches"], 500)
        self.assertEqual(report.blocker_count, 0, report.issues)
        self.assertLess(elapsed, 30)

    def test_100_batch_cpsat_acceptance(self):
        instance, report, _ = build_and_validate(
            horizon_start=DEMO_ORIGIN,
            horizon_days=45,
            freeze_hours=48,
            source=VALID_SOURCE,
        )
        self.assertEqual(report.blocker_count, 0, report.issues)
        started = perf_counter()
        solution = solve(instance, SolverParameters(max_time_seconds=30))
        elapsed = perf_counter() - started
        validation = SchedulingSolutionValidator().validate(instance, solution)
        self.assertIn(solution.status, ("FEASIBLE", "OPTIMAL"), solution.message)
        self.assertEqual(solution.scheduled_task_count, 500)
        self.assertEqual(validation.violation_count, 0, validation.violations)
        self.assertLess(
            solution.phase3b_metrics["furnace_load_count"],
            solution.phase3a_baseline_metrics["furnace_load_count"],
        )
        self.assertLessEqual(
            solution.phase3b_metrics["weighted_tardiness"],
            solution.phase3a_baseline_metrics["weighted_tardiness"],
        )
        self.assertLess(elapsed, 60)

    def test_500_batch_cpsat_acceptance(self):
        SolverDemoLoader().load_valid(500)
        instance, report, _ = build_and_validate(
            horizon_start=DEMO_ORIGIN,
            horizon_days=180,
            freeze_hours=48,
            source=VALID_SOURCE,
        )
        self.assertEqual(report.blocker_count, 0, report.issues)
        started = perf_counter()
        solution = solve(instance, SolverParameters(max_time_seconds=60))
        elapsed = perf_counter() - started
        validation = SchedulingSolutionValidator().validate(instance, solution)
        self.assertIn(solution.status, ("FEASIBLE", "OPTIMAL"), solution.message)
        self.assertEqual(solution.scheduled_task_count, 2500)
        self.assertEqual(validation.violation_count, 0, validation.violations)
        self.assertLess(
            solution.phase3b_metrics["furnace_load_count"],
            solution.phase3a_baseline_metrics["furnace_load_count"],
        )
        self.assertLessEqual(
            solution.phase3b_metrics["weighted_tardiness"],
            solution.phase3a_baseline_metrics["weighted_tardiness"],
        )
        self.assertLess(elapsed, 300)


class InvalidSolverDemoIntegrationTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.metadata = SolverDemoLoader().load_invalid()

    def test_invalid_demo_covers_every_major_precheck_code(self):
        _, report, _ = build_and_validate(
            horizon_start=DEMO_ORIGIN,
            horizon_days=14,
            freeze_hours=48,
            source=INVALID_SOURCE,
        )
        actual = {item.code for item in report.issues}
        expected = {f"MLCC-P{number:03d}" for number in range(1, 26)}
        self.assertEqual(actual, expected)
        self.assertGreater(report.blocker_count, 0)
        self.assertFalse(report.can_start_solver)

    def test_blocker_prevents_command_output(self):
        with TemporaryDirectory() as directory:
            output = Path(directory) / "must-not-exist.json"
            with self.assertRaises(CommandError):
                call_command(
                    "mlcc_build_instance",
                    start=DEMO_ORIGIN.isoformat(),
                    source=INVALID_SOURCE,
                    output=str(output),
                    no_persist=True,
                    verbosity=0,
                )
            self.assertFalse(output.exists())
