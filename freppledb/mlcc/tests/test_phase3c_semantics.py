from dataclasses import replace
from decimal import Decimal

from django.test import SimpleTestCase

from freppledb.mlcc.solver import phase3c
from freppledb.mlcc.solver.schema import CalendarInterval
from freppledb.mlcc.solver.serializer import to_primitive
from freppledb.mlcc.solver.solution import SolverParameters
from freppledb.mlcc.solver.solution_validator import SchedulingSolutionValidator
from freppledb.mlcc.solver.transition_rules import (
    resolve_transition_rule,
    transition_rule_snapshot,
)

from .test_cpsat_solver import two_batch_instance
from .test_furnace_transitions import transition_instance


OLD_RULE_ID = "transition_rule:v1-v2:old"
NEW_RULE_ID = "transition_rule:v1-v2:new"


def dated_rule_instance(origin, *, cross_boundary=False):
    instance = transition_instance(forward_minutes=60, dependency="forward")
    original = next(
        item
        for item in instance.furnace_transition_rules
        if item.id == "transition_rule:v1-v2"
    )
    rules = tuple(
        item
        for item in instance.furnace_transition_rules
        if item.id != original.id
    ) + (
        replace(
            original,
            id=OLD_RULE_ID,
            duration_minutes=7,
            setup_cost=Decimal("7"),
            effective_date="2025-01-01",
            expiry_date="2026-01-09",
        ),
        replace(
            original,
            id=NEW_RULE_ID,
            duration_minutes=91,
            setup_cost=Decimal("91"),
            effective_date="2026-01-10",
            expiry_date=None,
        ),
    )
    window = replace(
        instance.window,
        origin=origin,
        horizon_minutes=4320 if cross_boundary else instance.window.horizon_minutes,
    )
    if not cross_boundary:
        return replace(instance, window=window, furnace_transition_rules=rules)

    equipment = tuple(
        (
            replace(
                item,
                shifts=(CalendarInterval(1500, 4320, "shift"),),
            )
            if item.id == "resource:sintering"
            else replace(
                item,
                shifts=tuple(
                    replace(interval, end_minute=min(interval.end_minute, 4320))
                    for interval in item.shifts
                ),
            )
        )
        for item in instance.equipment
    )
    steps = tuple(
        replace(item, maximum_wait_minutes=None) for item in instance.steps
    )
    return replace(
        instance,
        window=window,
        equipment=equipment,
        steps=steps,
        furnace_transition_rules=rules,
    )


def business_solution_payload(solution):
    snapshot_keys = (
        "furnace_load_count",
        "furnace_load_count_source",
        "furnace_load_count_optimized",
        "transition_rule_resolution_mode",
        "transition_rule_snapshot_at",
        "transition_rule_snapshot_fingerprint",
        "effective_transition_rule_ids",
        "selected_transition_rule_ids",
    )
    return {
        "assignments": to_primitive(solution.assignments),
        "furnace_loads": to_primitive(solution.furnace_loads),
        "furnace_transitions": to_primitive(solution.furnace_transitions),
        "orders": to_primitive(solution.orders),
        "objective_stage_names": tuple(
            item.name for item in solution.objective_stages
        ),
        "objective_values": to_primitive(solution.objective_values),
        "semantic_metrics": {
            key: to_primitive(solution.phase3c_metrics.get(key))
            for key in snapshot_keys
        },
    }


class Phase3CSemanticClosureTest(SimpleTestCase):
    parameters = SolverParameters(max_time_seconds=8, num_search_workers=1)

    def test_furnace_load_count_is_reported_but_not_optimized(self):
        solution = phase3c.solve(two_batch_instance(), self.parameters)
        self.assertIn(solution.status, ("FEASIBLE", "OPTIMAL"), solution.message)
        self.assertNotIn(
            "furnace_load_count",
            tuple(item.name for item in solution.objective_stages),
        )
        self.assertEqual(
            tuple(item.name for item in solution.objective_stages),
            (
                "feasibility",
                "weighted_tardiness",
                "transition_minutes",
                "makespan",
            ),
        )
        self.assertIsNone(solution.fallback_reason)
        self.assertEqual(
            solution.phase3c_metrics["furnace_load_count"],
            len(solution.furnace_loads),
        )
        self.assertEqual(
            solution.phase3c_metrics["furnace_load_count_source"],
            "phase3b_inherited",
        )
        self.assertIs(
            solution.phase3c_metrics["furnace_load_count_optimized"],
            False,
        )
        self.assertEqual(
            phase3c._furnace_load_count_source(
                {"grouping_source": "deterministic_phase3c_preaggregation"}
            ),
            "deterministic_pregrouped",
        )

    def test_planning_origin_before_change_selects_old_rule(self):
        instance = dated_rule_instance("2026-01-09T00:00:00+08:00")
        snapshot = transition_rule_snapshot(instance)
        resolution = resolve_transition_rule(
            instance,
            "resource:sintering",
            "sintering",
            "sintering-done",
            "furnace_program:sintering-v2",
            snapshot,
        )
        self.assertEqual(snapshot.resolution_mode, "planning_origin_snapshot")
        self.assertEqual(resolution.rule.id, OLD_RULE_ID)

    def test_new_planning_origin_selects_new_rule(self):
        old_instance = dated_rule_instance("2026-01-09T00:00:00+08:00")
        new_instance = dated_rule_instance("2026-01-10T00:00:00+08:00")
        old_snapshot = transition_rule_snapshot(old_instance)
        new_snapshot = transition_rule_snapshot(new_instance)
        resolution = resolve_transition_rule(
            new_instance,
            "resource:sintering",
            "sintering",
            "sintering-done",
            "furnace_program:sintering-v2",
            new_snapshot,
        )
        self.assertEqual(resolution.rule.id, NEW_RULE_ID)
        self.assertNotEqual(old_snapshot.fingerprint, new_snapshot.fingerprint)

    def test_cross_boundary_solve_keeps_origin_snapshot(self):
        instance = dated_rule_instance(
            "2026-01-09T00:00:00+08:00",
            cross_boundary=True,
        )
        solution = phase3c.solve(instance, self.parameters)
        validation = SchedulingSolutionValidator().validate(instance, solution)
        transition = next(
            item
            for item in solution.furnace_transitions
            if item.rule_id == OLD_RULE_ID
        )
        self.assertGreaterEqual(transition.start_minute, 1500)
        self.assertEqual(transition.duration_minutes, 7)
        self.assertNotIn(
            NEW_RULE_ID,
            solution.phase3c_metrics["selected_transition_rule_ids"],
        )
        self.assertEqual(validation.violation_count, 0, validation.violations)

    def test_validator_rejects_a_different_rule_snapshot(self):
        instance = dated_rule_instance("2026-01-09T00:00:00+08:00")
        solution = phase3c.solve(instance, self.parameters)
        tampered = replace(
            solution,
            phase3c_metrics={
                **solution.phase3c_metrics,
                "transition_rule_snapshot_at": "2026-01-10T00:00:00+08:00",
            },
        )
        report = SchedulingSolutionValidator().validate(instance, tampered)
        self.assertIn("MLCC-SV047", {item.code for item in report.violations})

    def test_model_and_validator_share_snapshot_fingerprint(self):
        instance = dated_rule_instance("2026-01-09T00:00:00+08:00")
        snapshot = transition_rule_snapshot(instance)
        solution = phase3c.solve(instance, self.parameters)
        self.assertEqual(
            solution.phase3c_metrics["transition_rule_snapshot_fingerprint"],
            snapshot.fingerprint,
        )
        self.assertTrue(solution.furnace_transitions)
        self.assertTrue(
            all(
                item.resolution_evidence[
                    "transition_rule_snapshot_fingerprint"
                ]
                == snapshot.fingerprint
                for item in solution.furnace_transitions
            )
        )
        self.assertTrue(
            SchedulingSolutionValidator().validate(instance, solution).valid
        )

    def test_repeated_solve_has_stable_business_structure(self):
        instance = dated_rule_instance("2026-01-09T00:00:00+08:00")
        first = phase3c.solve(instance, self.parameters)
        second = phase3c.solve(instance, self.parameters)
        self.assertEqual(
            business_solution_payload(first),
            business_solution_payload(second),
        )
