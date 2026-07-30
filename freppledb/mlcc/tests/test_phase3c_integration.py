import json
from time import perf_counter

from django.test import TestCase

from freppledb.mlcc.demo import (
    DEMO_ORIGIN,
    SAME_PROGRAM_SOURCE,
    TRANSITION_SOURCE,
    SolverDemoLoader,
)
from freppledb.mlcc.models import (
    MlccFurnaceLoad,
    MlccFurnaceTransition,
    MlccScheduleResult,
)
from freppledb.mlcc.solver.phase3c import solve
from freppledb.mlcc.solver.service import build_and_validate
from freppledb.mlcc.solver.solution import SolverParameters
from freppledb.mlcc.solver.solution_validator import SchedulingSolutionValidator
from freppledb.mlcc.solver.solve_service import persist_preview_solution


class Phase3CPerformanceIntegrationTest(TestCase):
    def build(self, source):
        return build_and_validate(
            horizon_start=DEMO_ORIGIN,
            horizon_days=180,
            freeze_hours=48,
            source=source,
        )

    def test_same_program_demo_100_batches_matches_phase3b_hard_metrics(self):
        SolverDemoLoader().load_same_program(100)
        instance, report, precheck_ms = self.build(SAME_PROGRAM_SOURCE)
        self.assertEqual(report.blocker_count, 0, report.issues)
        started = perf_counter()
        solution = solve(
            instance,
            SolverParameters(max_time_seconds=120, num_search_workers=1),
        )
        elapsed = perf_counter() - started
        validation = SchedulingSolutionValidator().validate(instance, solution)
        self.assertIn(solution.status, ("FEASIBLE", "OPTIMAL"), solution.message)
        self.assertEqual(solution.scheduled_task_count, 500)
        self.assertEqual(validation.violation_count, 0, validation.violations)
        self.assertEqual(solution.phase3c_metrics["transition_minutes"], 0)
        self.assertLessEqual(
            solution.phase3c_metrics["weighted_tardiness"],
            solution.phase3b_reference_metrics["weighted_tardiness"],
        )
        self.assertLessEqual(
            solution.phase3c_metrics["furnace_load_count"],
            solution.phase3b_reference_metrics["furnace_load_count"],
        )
        self.assertLess(precheck_ms, 30000)
        self.assertLess(elapsed, 120)
        print(
            "PHASE3C_PERFORMANCE "
            + json.dumps(
                {
                    "dataset": "same_program_demo",
                    "batches": 100,
                    "tasks": solution.scheduled_task_count,
                    "precheck_ms": precheck_ms,
                    "solve_seconds": round(elapsed, 6),
                    "validator_violations": validation.violation_count,
                    "phase3b_reference": solution.phase3b_reference_metrics,
                    "phase3c": solution.phase3c_metrics,
                },
                sort_keys=True,
            )
        )

    def test_transition_demo_500_batches_is_c_feasible_within_300_seconds(self):
        SolverDemoLoader().load_transition(500)
        extraction_started = perf_counter()
        instance, report, precheck_ms = self.build(TRANSITION_SOURCE)
        extraction_and_precheck = perf_counter() - extraction_started
        self.assertEqual(report.blocker_count, 0, report.issues)
        started = perf_counter()
        solution = solve(
            instance,
            SolverParameters(max_time_seconds=300, num_search_workers=1),
        )
        elapsed = perf_counter() - started
        validation_started = perf_counter()
        validation = SchedulingSolutionValidator().validate(instance, solution)
        validator_elapsed = perf_counter() - validation_started
        self.assertIn(solution.status, ("FEASIBLE", "OPTIMAL"), solution.message)
        self.assertEqual(solution.scheduled_task_count, 2500)
        self.assertEqual(validation.violation_count, 0, validation.violations)
        self.assertTrue(solution.furnace_transitions)
        self.assertFalse(
            solution.phase3b_reference_metrics["valid_under_phase3c_constraints"]
        )
        self.assertEqual(
            solution.phase3b_reference_metrics["grouping_source"],
            "deterministic_phase3c_preaggregation",
        )
        self.assertLess(
            solution.phase3b_reference_metrics["grouping_furnace_load_count"],
            solution.phase3b_reference_metrics["raw_furnace_load_count"],
        )
        self.assertLess(precheck_ms, 30000)
        self.assertLess(extraction_and_precheck, 30)
        self.assertLess(elapsed, 300)
        self.assertLess(validator_elapsed, 30)
        persistence_started = perf_counter()
        run = persist_preview_solution(
            instance,
            solution,
            source=TRANSITION_SOURCE,
        )
        persistence_elapsed = perf_counter() - persistence_started
        self.assertEqual(
            MlccScheduleResult.objects.filter(run=run).count(),
            solution.scheduled_task_count,
        )
        self.assertEqual(
            MlccFurnaceLoad.objects.filter(run=run).count(),
            len([item for item in solution.furnace_loads if not item.frozen]),
        )
        self.assertEqual(
            MlccFurnaceTransition.objects.filter(run=run).count(),
            len(solution.furnace_transitions),
        )
        self.assertFalse(
            MlccScheduleResult.objects.filter(run=run)
            .exclude(status="proposed")
            .exists()
        )
        end_to_end = (
            extraction_and_precheck + elapsed + validator_elapsed + persistence_elapsed
        )
        print(
            "PHASE3C_PERFORMANCE "
            + json.dumps(
                {
                    "dataset": "transition_demo",
                    "batches": 500,
                    "tasks": solution.scheduled_task_count,
                    "extraction_and_precheck_seconds": round(
                        extraction_and_precheck, 6
                    ),
                    "precheck_ms": precheck_ms,
                    "solve_seconds": round(elapsed, 6),
                    "validator_seconds": round(validator_elapsed, 6),
                    "persistence_seconds": round(persistence_elapsed, 6),
                    "end_to_end_seconds": round(end_to_end, 6),
                    "validator_violations": validation.violation_count,
                    "phase3b_reference": solution.phase3b_reference_metrics,
                    "phase3c": solution.phase3c_metrics,
                },
                sort_keys=True,
            )
        )
