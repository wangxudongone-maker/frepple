from dataclasses import replace
from decimal import Decimal
from unittest.mock import patch

from django.test import SimpleTestCase

from freppledb.mlcc.solver import phase3c
from freppledb.mlcc.solver.constraints import available_segments
from freppledb.mlcc.solver.schema import (
    CalendarInterval,
    EquipmentCapability,
    FrozenFurnaceLoad,
    FrozenFurnaceTransition,
    FurnaceProgram,
    FurnaceStateSnapshot,
    FurnaceTransitionRule,
    Recipe,
)
from freppledb.mlcc.solver.solution import SolverParameters
from freppledb.mlcc.solver.solution_validator import SchedulingSolutionValidator
from freppledb.mlcc.solver.transition_rules import resolve_transition_rule
from freppledb.mlcc.solver.validator import PlanningInstanceValidator

from .test_cpsat_solver import two_batch_instance
from .test_solver_validator import valid_instance


def transition_instance(
    *,
    forward_minutes=60,
    reverse_minutes=15,
    dependency="forward",
):
    instance = two_batch_instance()
    program = FurnaceProgram(
        id="furnace_program:sintering-v2",
        program_key="SINTERING-V2",
        version="V2",
        stage="sintering",
        atmosphere_key="N2",
        required_pre_state_key="sintering-done",
        resulting_post_state_key="sintering-v2-done",
        effective_date="2025-01-01",
        expiry_date=None,
        active=True,
    )
    recipe = Recipe(
        id="recipe:sintering-v2",
        name="sintering",
        version="V2",
        stage="sintering",
        effective_date="2025-01-01",
        expiry_date=None,
        active=True,
        setup_family="sintering-b",
        furnace_program_key=program.program_key,
        furnace_program_id=program.id,
        compatibility_group="CERAMIC-A",
    )
    first_id = "task:5"
    second_id = "task:5:b2"
    steps = []
    for step in instance.steps:
        if step.id == second_id:
            predecessors = step.predecessor_ids
            if dependency == "forward":
                predecessors = tuple(sorted(set(predecessors + (first_id,))))
            steps.append(
                replace(
                    step,
                    recipe_id=recipe.id,
                    predecessor_ids=predecessors,
                )
            )
        elif step.id == first_id and dependency == "reverse":
            steps.append(
                replace(
                    step,
                    predecessor_ids=tuple(
                        sorted(set(step.predecessor_ids + (second_id,)))
                    ),
                )
            )
        else:
            steps.append(step)
    capability = EquipmentCapability(
        id="capability:sintering-v2",
        resource_id="resource:sintering",
        stage="sintering",
        recipe_id=recipe.id,
        item_id="item:finished",
        minimum_quantity=Decimal("1"),
        maximum_quantity=Decimal("1000"),
        enabled=True,
    )
    rules = (
        FurnaceTransitionRule(
            id="transition_rule:initial-v2",
            resource_id="resource:sintering",
            equipment_group=None,
            stage="sintering",
            from_state_key="sintering-idle",
            to_program_id=program.id,
            transition_type="atmosphere_purge",
            duration_minutes=5,
            setup_cost=Decimal("5"),
            allowed=True,
            enabled=True,
            priority=0,
            effective_date="2025-01-01",
            expiry_date=None,
            scope_level="resource",
        ),
        FurnaceTransitionRule(
            id="transition_rule:v1-v2",
            resource_id="resource:sintering",
            equipment_group=None,
            stage="sintering",
            from_state_key="sintering-done",
            to_program_id=program.id,
            transition_type="cleaning",
            duration_minutes=forward_minutes,
            setup_cost=Decimal(forward_minutes),
            allowed=True,
            enabled=True,
            priority=0,
            effective_date="2025-01-01",
            expiry_date=None,
            scope_level="resource",
        ),
        FurnaceTransitionRule(
            id="transition_rule:v2-v1",
            resource_id="resource:sintering",
            equipment_group=None,
            stage="sintering",
            from_state_key="sintering-v2-done",
            to_program_id="furnace_program:sintering-v1",
            transition_type="atmosphere_purge",
            duration_minutes=reverse_minutes,
            setup_cost=Decimal(reverse_minutes),
            allowed=True,
            enabled=True,
            priority=0,
            effective_date="2025-01-01",
            expiry_date=None,
            scope_level="resource",
        ),
        FurnaceTransitionRule(
            id="transition_rule:v2-self",
            resource_id="resource:sintering",
            equipment_group=None,
            stage="sintering",
            from_state_key="sintering-v2-done",
            to_program_id=program.id,
            transition_type="none",
            duration_minutes=0,
            setup_cost=Decimal("0"),
            allowed=True,
            enabled=True,
            priority=0,
            effective_date="2025-01-01",
            expiry_date=None,
            scope_level="resource",
        ),
    )
    return replace(
        instance,
        steps=tuple(steps),
        recipes=instance.recipes + (recipe,),
        furnace_programs=instance.furnace_programs + (program,),
        capabilities=instance.capabilities + (capability,),
        furnace_transition_rules=instance.furnace_transition_rules + rules,
    )


def add_second_sintering_furnace(instance):
    original = next(
        item for item in instance.equipment if item.id == "resource:sintering"
    )
    second = replace(
        original,
        id="resource:sintering-2",
        resource_id="sintering-2",
    )
    steps = tuple(
        (
            replace(
                step,
                candidate_resource_ids=tuple(
                    sorted(step.candidate_resource_ids + (second.id,))
                ),
                certified_resource_ids=tuple(
                    sorted(step.certified_resource_ids + (second.id,))
                ),
                load_requirements=step.load_requirements
                + (
                    replace(
                        step.load_requirements[0],
                        resource_id=second.id,
                    ),
                ),
            )
            if step.stage == "sintering"
            else step
        )
        for step in instance.steps
    )
    capabilities = instance.capabilities + tuple(
        replace(
            item,
            id=f"{item.id}:second",
            resource_id=second.id,
        )
        for item in instance.capabilities
        if item.stage == "sintering"
    )
    state = replace(
        next(
            item
            for item in instance.furnace_state_snapshots
            if item.resource_id == original.id
        ),
        id="furnace_state:sintering-2",
        resource_id=second.id,
    )
    second_rules = tuple(
        replace(
            item,
            id=f"{item.id}:second",
            resource_id=second.id,
        )
        for item in instance.furnace_transition_rules
        if item.resource_id == original.id
    )
    return replace(
        instance,
        equipment=instance.equipment + (second,),
        steps=steps,
        capabilities=capabilities,
        furnace_state_snapshots=instance.furnace_state_snapshots + (state,),
        furnace_transition_rules=(instance.furnace_transition_rules + second_rules),
    )


class FurnaceTransitionGoldTest(SimpleTestCase):
    parameters = SolverParameters(max_time_seconds=8, num_search_workers=1)

    def solve_valid(self, instance):
        report = PlanningInstanceValidator().validate(instance)
        self.assertEqual(report.blocker_count, 0, report.issues)
        solution = phase3c.solve(instance, self.parameters)
        validation = SchedulingSolutionValidator().validate(instance, solution)
        self.assertIn(solution.status, ("FEASIBLE", "OPTIMAL"), solution.message)
        self.assertEqual(validation.violation_count, 0, validation.violations)
        return solution

    @staticmethod
    def sintering_transitions(solution):
        load_stage = {
            item.load_id: item.operation_type for item in solution.furnace_loads
        }
        return [
            item
            for item in solution.furnace_transitions
            if load_stage[item.successor_load_id] == "sintering"
        ]

    def test_explicit_zero_self_transition_matches_phase3b_metrics(self):
        solution = self.solve_valid(two_batch_instance())
        self.assertEqual(
            solution.phase3c_metrics["weighted_tardiness"],
            solution.phase3b_reference_metrics["weighted_tardiness"],
        )
        self.assertEqual(
            solution.phase3c_metrics["furnace_load_count"],
            solution.phase3b_reference_metrics["furnace_load_count"],
        )
        self.assertEqual(
            sum(item.duration_minutes for item in solution.furnace_transitions),
            0,
        )

    def test_forward_cleaning_requires_sixty_minute_gap(self):
        solution = self.solve_valid(transition_instance(forward_minutes=60))
        transition = next(
            item
            for item in self.sintering_transitions(solution)
            if item.rule_id == "transition_rule:v1-v2"
        )
        loads = {item.load_id: item for item in solution.furnace_loads}
        self.assertEqual(transition.duration_minutes, 60)
        self.assertGreaterEqual(
            loads[transition.successor_load_id].start_minute,
            loads[transition.predecessor_load_id].end_minute + 60,
        )

    def test_directional_rules_are_not_symmetrized(self):
        solution = self.solve_valid(
            transition_instance(
                forward_minutes=60,
                reverse_minutes=15,
                dependency="reverse",
            )
        )
        transition = next(
            item
            for item in self.sintering_transitions(solution)
            if item.predecessor_load_id
        )
        self.assertEqual(transition.rule_id, "transition_rule:v2-v1")
        self.assertEqual(transition.duration_minutes, 15)

    def test_resource_rule_overrides_group_and_global(self):
        instance = transition_instance()
        target = "furnace_program:sintering-v2"
        rules = instance.furnace_transition_rules + (
            FurnaceTransitionRule(
                id="transition_rule:global",
                resource_id=None,
                equipment_group=None,
                stage="sintering",
                from_state_key="sintering-done",
                to_program_id=target,
                transition_type="cleaning",
                duration_minutes=90,
                setup_cost=Decimal("90"),
                allowed=True,
                enabled=True,
                priority=0,
                effective_date="2025-01-01",
                expiry_date=None,
                scope_level="global",
            ),
            FurnaceTransitionRule(
                id="transition_rule:group",
                resource_id=None,
                equipment_group="furnace-group",
                stage="sintering",
                from_state_key="sintering-done",
                to_program_id=target,
                transition_type="cleaning",
                duration_minutes=75,
                setup_cost=Decimal("75"),
                allowed=True,
                enabled=True,
                priority=0,
                effective_date="2025-01-01",
                expiry_date=None,
                scope_level="equipment_group",
            ),
        )
        resolution = resolve_transition_rule(
            replace(instance, furnace_transition_rules=rules),
            "resource:sintering",
            "sintering",
            "sintering-done",
            target,
        )
        self.assertEqual(resolution.rule.id, "transition_rule:v1-v2")
        self.assertEqual(resolution.scope_level, "resource")

    def test_missing_forward_rule_forbids_that_adjacency(self):
        instance = transition_instance(dependency="forward")
        instance = replace(
            instance,
            furnace_transition_rules=tuple(
                item
                for item in instance.furnace_transition_rules
                if item.id != "transition_rule:v1-v2"
            ),
        )
        report = PlanningInstanceValidator().validate(instance)
        self.assertEqual(report.blocker_count, 0, report.issues)
        solution = phase3c.solve(instance, self.parameters)
        self.assertEqual(solution.status, "INFEASIBLE")
        self.assertFalse(solution.assignments)

    def test_second_furnace_is_selected_when_only_it_has_target_rules(self):
        instance = add_second_sintering_furnace(transition_instance())
        instance = replace(
            instance,
            furnace_transition_rules=tuple(
                item
                for item in instance.furnace_transition_rules
                if not (
                    item.resource_id == "resource:sintering"
                    and item.to_program_id == "furnace_program:sintering-v2"
                )
            ),
        )
        solution = self.solve_valid(instance)
        target_load = next(
            item
            for item in solution.furnace_loads
            if item.furnace_program_id == "furnace_program:sintering-v2"
        )
        self.assertEqual(target_load.equipment_id, "resource:sintering-2")

    def test_all_candidate_furnaces_unreachable_returns_p024(self):
        instance = transition_instance()
        instance = replace(
            instance,
            furnace_transition_rules=tuple(
                item
                for item in instance.furnace_transition_rules
                if item.to_program_id != "furnace_program:sintering-v2"
            ),
        )
        report = PlanningInstanceValidator().validate(instance)
        self.assertIn("MLCC-P024", {item.code for item in report.issues})

    def test_initial_atmosphere_purge_precedes_first_load(self):
        instance = valid_instance()
        rules = tuple(
            (
                replace(
                    item,
                    transition_type="atmosphere_purge",
                    duration_minutes=30,
                    setup_cost=Decimal("30"),
                )
                if item.id == "transition_rule:sintering-initial"
                else item
            )
            for item in instance.furnace_transition_rules
        )
        solution = self.solve_valid(replace(instance, furnace_transition_rules=rules))
        transition = self.sintering_transitions(solution)[0]
        load = next(
            item
            for item in solution.furnace_loads
            if item.load_id == transition.successor_load_id
        )
        self.assertEqual(transition.duration_minutes, 30)
        self.assertEqual(transition.end_minute, load.start_minute)

    def test_transition_does_not_overlap_downtime(self):
        instance = valid_instance()
        equipment = tuple(
            (
                replace(
                    item,
                    downtimes=(CalendarInterval(200, 260, "downtime"),),
                )
                if item.id == "resource:sintering"
                else item
            )
            for item in instance.equipment
        )
        rules = tuple(
            (
                replace(
                    item,
                    transition_type="cleaning",
                    duration_minutes=60,
                    setup_cost=Decimal("60"),
                )
                if item.id == "transition_rule:sintering-initial"
                else item
            )
            for item in instance.furnace_transition_rules
        )
        changed = replace(
            instance,
            equipment=equipment,
            furnace_transition_rules=rules,
        )
        solution = self.solve_valid(changed)
        transition = self.sintering_transitions(solution)[0]
        resource = next(
            item for item in changed.equipment if item.id == transition.equipment_id
        )
        self.assertTrue(
            any(
                start <= transition.start_minute and transition.end_minute <= end
                for start, end in available_segments(
                    resource, changed.window.horizon_minutes
                )
            )
        )

    def test_frozen_load_and_transition_are_unchanged(self):
        instance = valid_instance()
        step = next(item for item in instance.steps if item.stage == "sintering")
        frozen_step = replace(
            step,
            frozen=True,
            assigned_resource_id="resource:sintering",
        )
        load = FrozenFurnaceLoad(
            id="furnace_load:frozen",
            stage="sintering",
            resource_id="resource:sintering",
            recipe_id="recipe:sintering",
            furnace_program_key="SINTERING-V1",
            start_minute=step.original_start_minute,
            end_minute=step.original_end_minute,
            capacity=1000,
            loaded_quantity=1,
            load_unit="tray",
            member_task_ids=(step.id,),
            status="running",
            furnace_program_id="furnace_program:sintering-v1",
        )
        transition = FrozenFurnaceTransition(
            id="furnace_transition:frozen",
            resource_id=load.resource_id,
            predecessor_load_id=None,
            successor_load_id=load.id,
            transition_rule_id="transition_rule:sintering-initial",
            transition_type="none",
            start_minute=load.start_minute,
            end_minute=load.start_minute,
            status="proposed",
        )
        changed = replace(
            instance,
            steps=tuple(
                frozen_step if item.id == step.id else item for item in instance.steps
            ),
            frozen_furnace_loads=(load,),
            frozen_furnace_transitions=(transition,),
        )
        solution = self.solve_valid(changed)
        actual_load = next(
            item for item in solution.furnace_loads if item.load_id == load.id
        )
        actual_transition = next(
            item
            for item in solution.furnace_transitions
            if item.transition_id == transition.id
        )
        self.assertEqual(actual_load.equipment_id, load.resource_id)
        self.assertEqual(actual_load.start_minute, load.start_minute)
        self.assertEqual(actual_load.member_task_ids, load.member_task_ids)
        self.assertTrue(actual_transition.frozen)
        self.assertEqual(actual_transition.start_minute, transition.start_minute)

    def test_grouped_members_do_not_create_internal_transitions(self):
        solution = self.solve_valid(two_batch_instance())
        load = next(
            item
            for item in solution.furnace_loads
            if item.operation_type == "sintering"
        )
        self.assertEqual(len(load.member_task_ids), 2)
        incoming = [
            item
            for item in solution.furnace_transitions
            if item.successor_load_id == load.load_id
        ]
        self.assertEqual(len(incoming), 1)

    def test_mixed_recipes_on_one_program_have_no_fake_recipe(self):
        instance = two_batch_instance()
        recipe = replace(
            next(item for item in instance.recipes if item.stage == "sintering"),
            id="recipe:sintering-alias",
            name="sintering-alias",
            version="ALIAS",
        )
        steps = tuple(
            (
                replace(item, recipe_id=recipe.id)
                if item.batch_id == "batch:b2" and item.stage == "sintering"
                else item
            )
            for item in instance.steps
        )
        capability = replace(
            next(item for item in instance.capabilities if item.stage == "sintering"),
            id="capability:sintering-alias",
            recipe_id=recipe.id,
        )
        solution = self.solve_valid(
            replace(
                instance,
                steps=steps,
                recipes=instance.recipes + (recipe,),
                capabilities=instance.capabilities + (capability,),
            )
        )
        load = next(
            item
            for item in solution.furnace_loads
            if item.operation_type == "sintering"
        )
        self.assertIsNone(load.recipe_id)
        self.assertIsNone(load.recipe_version)
        self.assertEqual(
            load.member_recipe_ids,
            ("recipe:sintering", "recipe:sintering-alias"),
        )

    def test_model_build_error_is_model_invalid_without_phase3a_fallback(self):
        instance = valid_instance()
        with patch.object(
            phase3c,
            "_build_model",
            side_effect=phase3c.ModelBuildError("intentional model error"),
        ):
            solution = phase3c.solve(instance, self.parameters)
        self.assertEqual(solution.status, "MODEL_INVALID")
        self.assertEqual(solution.solution_mode, "phase3c_transition")
        self.assertFalse(solution.assignments)
        self.assertIsNone(solution.fallback_reason)

    def test_timeout_fallback_is_a_phase3c_validated_snapshot(self):
        instance = valid_instance()
        original = phase3c._configure_solver
        calls = {"count": 0}

        def configure(parameters, limit):
            calls["count"] += 1
            solver = original(parameters, limit)
            if calls["count"] > 1:
                solver.parameters.max_time_in_seconds = 0.000001
            return solver

        with patch.object(phase3c, "_configure_solver", side_effect=configure):
            solution = phase3c.solve(instance, self.parameters)
        self.assertEqual(solution.status, "FEASIBLE")
        self.assertEqual(solution.solution_mode, "phase3c_transition")
        self.assertIsNotNone(solution.fallback_reason)
        self.assertTrue(
            SchedulingSolutionValidator().validate(instance, solution).valid
        )
