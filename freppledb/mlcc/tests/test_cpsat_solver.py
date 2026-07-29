import ast
import inspect
from dataclasses import replace
from unittest.mock import patch

from django.test import SimpleTestCase
from ortools.sat.python import cp_model

from freppledb.mlcc.solver import cpsat
from freppledb.mlcc.solver.cpsat import PrecheckBlockedError, solve
from freppledb.mlcc.solver.serializer import (
    planning_instance_fingerprint,
    planning_instance_from_json,
    planning_instance_json,
)
from freppledb.mlcc.solver.solution import (
    SolverParameters,
    scheduling_solution_json,
)
from freppledb.mlcc.solver.solution_validator import SchedulingSolutionValidator

from .test_solver_validator import valid_instance


def two_batch_instance():
    instance = valid_instance()
    second_order = replace(
        instance.customer_orders[0],
        id="order:o2",
        batch_id="batch:b2",
        priority=2,
    )
    second_batch = replace(
        instance.batches[0],
        id="batch:b2",
        order_id="order:o2",
        priority=2,
    )
    id_map = {step.id: f"{step.id}:b2" for step in instance.steps}
    second_steps = tuple(
        replace(
            step,
            id=id_map[step.id],
            batch_id="batch:b2",
            predecessor_ids=tuple(id_map[item] for item in step.predecessor_ids),
            original_start_minute=(
                None
                if step.original_start_minute is None
                else step.original_start_minute + 10
            ),
            original_end_minute=(
                None
                if step.original_end_minute is None
                else step.original_end_minute + 10
            ),
        )
        for step in instance.steps
    )
    return replace(
        instance,
        customer_orders=instance.customer_orders + (second_order,),
        batches=instance.batches + (second_batch,),
        steps=instance.steps + second_steps,
    )


class CpSatPureSolverTest(SimpleTestCase):
    def setUp(self):
        self.parameters = SolverParameters(max_time_seconds=5)
        self.validator = SchedulingSolutionValidator()

    def test_small_hand_checkable_schedule(self):
        instance = valid_instance()
        solution = solve(instance, self.parameters)
        self.assertIn(solution.status, ("FEASIBLE", "OPTIMAL"))
        self.assertEqual(solution.scheduled_task_count, 5)
        self.assertEqual(
            solution.input_fingerprint, planning_instance_fingerprint(instance)
        )
        self.assertEqual(
            [item.name for item in solution.objective_stages],
            [
                "feasibility",
                "weighted_tardiness",
                "furnace_load_count",
                "makespan",
            ],
        )
        assignments = {item.task_id: item for item in solution.assignments}
        self.assertEqual(assignments["task:1"].start_minute, 0)
        self.assertEqual(assignments["task:5"].end_minute, 300)
        self.assertEqual(solution.objective_values["weighted_tardiness"], 0)
        self.assertEqual(solution.objective_values["makespan"], 300)
        self.assertTrue(self.validator.validate(instance, solution).valid)

    def test_resource_calendar_and_precedence_are_hard_constraints(self):
        instance = valid_instance()
        equipment = (
            instance.equipment[:1]
            + (
                replace(
                    instance.equipment[1],
                    downtimes=(
                        replace(
                            instance.equipment[1].shifts[0],
                            start_minute=0,
                            end_minute=180,
                            kind="downtime",
                        ),
                    ),
                ),
            )
            + instance.equipment[2:]
        )
        instance = replace(instance, equipment=equipment)
        solution = solve(instance, self.parameters)
        assignments = {item.task_id: item for item in solution.assignments}
        self.assertGreaterEqual(assignments["task:2"].start_minute, 180)
        self.assertTrue(self.validator.validate(instance, solution).valid)

    def test_frozen_task_is_not_moved(self):
        instance = valid_instance()
        frozen = replace(
            instance.steps[0],
            frozen=True,
            assigned_resource_id="resource:stacking",
        )
        instance = replace(instance, steps=(frozen,) + instance.steps[1:])
        solution = solve(instance, self.parameters)
        assignment = next(
            item for item in solution.assignments if item.task_id == frozen.id
        )
        self.assertEqual(assignment.resource_id, frozen.assigned_resource_id)
        self.assertEqual(assignment.start_minute, frozen.original_start_minute)
        self.assertEqual(assignment.end_minute, frozen.original_end_minute)
        self.assertTrue(self.validator.validate(instance, solution).valid)

    def test_two_compatible_furnace_batches_share_explicit_load(self):
        instance = two_batch_instance()
        solution = solve(instance, self.parameters)
        self.assertIn(solution.status, ("FEASIBLE", "OPTIMAL"))
        furnace = [item for item in solution.assignments if item.stage == "sintering"]
        self.assertEqual(len(furnace), 2)
        self.assertEqual(furnace[0].furnace_load_id, furnace[1].furnace_load_id)
        self.assertEqual(furnace[0].start_minute, furnace[1].start_minute)
        self.assertEqual(furnace[0].end_minute, furnace[1].end_minute)
        self.assertEqual(solution.parameters.furnace_mode, "multi_batch_loads")
        self.assertEqual(solution.solution_mode, "phase3b_multi_batch")
        self.assertIsNone(solution.fallback_reason)
        self.assertEqual(solution.last_successful_stage, "makespan")
        self.assertLess(
            solution.phase3b_metrics["furnace_load_count"],
            solution.phase3a_baseline_metrics["furnace_load_count"],
        )
        self.assertTrue(self.validator.validate(instance, solution).valid)

    def test_blockers_refuse_solver_even_after_json_round_trip(self):
        instance = valid_instance()
        invalid = replace(
            instance,
            steps=(replace(instance.steps[0], duration_minutes=0),)
            + instance.steps[1:],
        )
        loaded = planning_instance_from_json(planning_instance_json(invalid))
        with self.assertRaises(PrecheckBlockedError):
            solve(loaded, self.parameters)

    def test_model_invalid_and_infeasible_are_explicit(self):
        instance = valid_instance()
        missing_fixed_data = replace(instance.steps[0], frozen=True)
        model_invalid = solve(
            replace(instance, steps=(missing_fixed_data,) + instance.steps[1:]),
            self.parameters,
        )
        self.assertEqual(model_invalid.status, "MODEL_INVALID")
        self.assertIn("requires resource", model_invalid.message)
        self.assertEqual(model_invalid.parameters.furnace_mode, "one_batch_per_run")
        self.assertEqual(model_invalid.solution_mode, "phase3a_fallback")
        self.assertEqual(
            model_invalid.fallback_reason,
            "phase3a_baseline_model_invalid",
        )

        short_window = replace(
            instance.window,
            horizon_minutes=200,
        )
        infeasible = solve(
            replace(instance, window=short_window),
            self.parameters,
        )
        self.assertEqual(infeasible.status, "INFEASIBLE")
        self.assertEqual(cpsat._status_name(cp_model.UNKNOWN), "UNKNOWN")

    def test_phase3b_model_build_error_never_silently_falls_back(self):
        instance = valid_instance()
        with patch.object(
            cpsat,
            "_build_model",
            side_effect=cpsat.ModelBuildError("deliberately broken phase-3B model"),
        ):
            solution = solve(instance, self.parameters)
        self.assertEqual(solution.status, "MODEL_INVALID")
        self.assertEqual(solution.solution_mode, "phase3b_multi_batch")
        self.assertEqual(solution.parameters.furnace_mode, "multi_batch_loads")
        self.assertIsNone(solution.fallback_reason)
        self.assertIn("deliberately broken", solution.message)
        self.assertEqual(solution.scheduled_task_count, 0)

    def test_time_limit_fallback_records_actual_mode_and_provenance(self):
        instance = valid_instance()
        baseline_parameters = replace(
            self.parameters,
            furnace_mode="one_batch_per_run",
        )
        baseline = cpsat.phase3a.solve(instance, baseline_parameters)
        self.assertIn(baseline.status, ("FEASIBLE", "OPTIMAL"))
        with (
            patch.object(cpsat.phase3a, "solve", return_value=baseline),
            patch.object(cpsat, "perf_counter", side_effect=(0.0, 100.0)),
        ):
            solution = solve(instance, self.parameters)
        self.assertEqual(solution.solution_mode, "phase3a_fallback")
        self.assertEqual(solution.parameters.furnace_mode, "one_batch_per_run")
        self.assertEqual(
            solution.fallback_reason,
            "phase3b_time_limit_exhausted_before_model",
        )
        self.assertIsNotNone(solution.last_successful_stage)
        self.assertTrue(self.validator.validate(instance, solution).valid)

    def test_json_round_trip_and_metadata_are_deterministic(self):
        instance = valid_instance()
        loaded = planning_instance_from_json(planning_instance_json(instance))
        self.assertEqual(instance, loaded)
        first = solve(instance, self.parameters)
        second = solve(loaded, self.parameters)
        self.assertEqual(first.input_fingerprint, second.input_fingerprint)
        self.assertEqual(first.solver_version, second.solver_version)
        self.assertEqual(first.parameters, second.parameters)
        self.assertIn(
            '"furnace_mode":"multi_batch_loads"', scheduling_solution_json(first)
        )
        self.assertIn(
            '"solution_mode":"phase3b_multi_batch"',
            scheduling_solution_json(first),
        )

    def test_pure_solver_has_no_django_or_orm_dependency(self):
        source = inspect.getsource(cpsat)
        tree = ast.parse(source)
        imported_modules = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported_modules.append(node.module or "")
        self.assertFalse(
            any(
                name == "django" or name.startswith("django.")
                for name in imported_modules
            )
        )
        self.assertNotIn("objects.", source)
