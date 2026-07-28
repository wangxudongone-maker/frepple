from dataclasses import replace
from decimal import Decimal

from django.test import SimpleTestCase

from freppledb.mlcc.solver.cpsat import solve
from freppledb.mlcc.solver.reasons import Severity
from freppledb.mlcc.solver.schema import (
    CompatibilityRule,
    EquipmentCapability,
    FrozenFurnaceLoad,
    FurnaceLoadRequirement,
    Recipe,
)
from freppledb.mlcc.solver.solution import SolverParameters
from freppledb.mlcc.solver.solution_validator import SchedulingSolutionValidator
from freppledb.mlcc.solver.validator import PlanningInstanceValidator

from .test_cpsat_solver import two_batch_instance
from .test_solver_validator import valid_instance


def clone_batch(instance, source_batch, suffix, family=None):
    source = next(item for item in instance.batches if item.id == source_batch)
    source_order = next(
        item for item in instance.customer_orders if item.id == source.order_id
    )
    batch_id = f"batch:{suffix}"
    order_id = f"order:{suffix}"
    id_map = {
        step.id: f"{step.id}:{suffix}"
        for step in instance.steps
        if step.batch_id == source_batch
    }
    steps = tuple(
        replace(
            step,
            id=id_map[step.id],
            batch_id=batch_id,
            predecessor_ids=tuple(id_map[item] for item in step.predecessor_ids),
        )
        for step in instance.steps
        if step.batch_id == source_batch
    )
    return replace(
        instance,
        customer_orders=instance.customer_orders
        + (
            replace(
                source_order,
                id=order_id,
                batch_id=batch_id,
                priority=len(instance.customer_orders) + 1,
            ),
        ),
        batches=instance.batches
        + (
            replace(
                source,
                id=batch_id,
                order_id=order_id,
                product_family=family or source.product_family,
                priority=len(instance.batches) + 1,
            ),
        ),
        steps=instance.steps + steps,
    )


class FurnaceBatchingGoldTest(SimpleTestCase):
    parameters = SolverParameters(max_time_seconds=8, num_search_workers=1)

    def solve_valid(self, instance):
        report = PlanningInstanceValidator().validate(instance)
        self.assertEqual(report.blocker_count, 0, report.issues)
        solution = solve(instance, self.parameters)
        validation = SchedulingSolutionValidator().validate(instance, solution)
        self.assertIn(solution.status, ("FEASIBLE", "OPTIMAL"), solution.message)
        self.assertEqual(validation.violation_count, 0, validation.violations)
        return solution

    def stage_loads(self, solution, stage="sintering"):
        return [item for item in solution.furnace_loads if item.operation_type == stage]

    def test_compatible_batches_merge_when_capacity_allows(self):
        instance = two_batch_instance()
        solution = self.solve_valid(instance)
        loads = self.stage_loads(solution)
        self.assertEqual(len(loads), 1)
        self.assertEqual(len(loads[0].member_batch_ids), 2)
        self.assertIn("utilization", solution.phase3a_baseline_metrics)
        self.assertIn("utilization", solution.phase3b_metrics)
        self.assertIn("utilization_ppm", solution.metric_deltas)
        self.assertIsNotNone(solution.optimality_gap)
        tampered_load = replace(
            loads[0],
            member_task_ids=loads[0].member_task_ids[:-1],
        )
        tampered = replace(
            solution,
            furnace_loads=tuple(
                tampered_load if item.load_id == loads[0].load_id else item
                for item in solution.furnace_loads
            ),
        )
        report = SchedulingSolutionValidator().validate(instance, tampered)
        self.assertIn("MLCC-SV022", {item.code for item in report.violations})

    def test_capacity_shortage_splits_loads(self):
        instance = two_batch_instance()
        equipment = tuple(
            (
                replace(item, capacity=Decimal("1"))
                if item.id == "resource:sintering"
                else item
            )
            for item in instance.equipment
        )
        solution = self.solve_valid(replace(instance, equipment=equipment))
        self.assertEqual(len(self.stage_loads(solution)), 2)

    def test_forbidden_families_never_share_load(self):
        instance = two_batch_instance()
        batches = tuple(
            replace(item, product_family="C0G") if item.id == "batch:b2" else item
            for item in instance.batches
        )
        solution = self.solve_valid(replace(instance, batches=batches))
        self.assertEqual(len(self.stage_loads(solution)), 2)

    def test_pairwise_compatibility_is_not_transitive(self):
        instance = clone_batch(two_batch_instance(), "batch:b1", "b3", "C")
        families = {"batch:b1": "A", "batch:b2": "B", "batch:b3": "C"}
        batches = tuple(
            replace(item, product_family=families[item.id]) for item in instance.batches
        )
        recipes = tuple(
            replace(item, compatibility_group=None) for item in instance.recipes
        )
        rules = tuple(
            CompatibilityRule(
                id=f"compatibility:{left}-{right}",
                stage="sintering",
                family_a=left,
                family_b=right,
                rule_type=rule_type,
                enabled=True,
            )
            for left, right, rule_type in (
                ("A", "B", "allow"),
                ("B", "C", "allow"),
                ("A", "C", "forbid"),
            )
        )
        solution = self.solve_valid(
            replace(
                instance,
                batches=batches,
                recipes=recipes,
                compatibility_rules=rules,
            )
        )
        loads = self.stage_loads(solution)
        self.assertGreaterEqual(len(loads), 2)
        self.assertLess(max(len(item.member_batch_ids) for item in loads), 3)

    def test_same_display_name_different_program_version_does_not_merge(self):
        instance = two_batch_instance()
        second_recipe = Recipe(
            id="recipe:sintering-v2",
            name="sintering",
            version="V2",
            stage="sintering",
            effective_date="2025-01-01",
            expiry_date=None,
            active=True,
            setup_family="sintering-a",
            furnace_program_key="SINTERING-V2",
            compatibility_group="CERAMIC-A",
        )
        steps = tuple(
            (
                replace(item, recipe_id=second_recipe.id)
                if item.batch_id == "batch:b2" and item.stage == "sintering"
                else item
            )
            for item in instance.steps
        )
        capability = EquipmentCapability(
            id="capability:sintering-v2",
            resource_id="resource:sintering",
            stage="sintering",
            recipe_id=second_recipe.id,
            item_id="item:finished",
            minimum_quantity=Decimal("1"),
            maximum_quantity=Decimal("1000"),
            enabled=True,
        )
        solution = self.solve_valid(
            replace(
                instance,
                steps=steps,
                recipes=instance.recipes + (second_recipe,),
                capabilities=instance.capabilities + (capability,),
            )
        )
        self.assertEqual(len(self.stage_loads(solution)), 2)

    def test_different_capacity_candidate_furnaces_remain_capacity_feasible(self):
        instance = two_batch_instance()
        small = next(
            item for item in instance.equipment if item.id == "resource:sintering"
        )
        large = replace(
            small,
            id="resource:sintering-large",
            resource_id="sintering-large",
            capacity=Decimal("2"),
        )
        equipment = tuple(
            replace(item, capacity=Decimal("1")) if item.id == small.id else item
            for item in instance.equipment
        ) + (large,)
        steps = tuple(
            (
                replace(
                    item,
                    candidate_resource_ids=tuple(
                        sorted(item.candidate_resource_ids + (large.id,))
                    ),
                    certified_resource_ids=tuple(
                        sorted(item.certified_resource_ids + (large.id,))
                    ),
                    load_requirements=item.load_requirements
                    + (
                        replace(
                            item.load_requirements[0],
                            resource_id=large.id,
                        ),
                    ),
                )
                if item.stage == "sintering"
                else item
            )
            for item in instance.steps
        )
        capability = replace(
            next(item for item in instance.capabilities if item.stage == "sintering"),
            id="capability:sintering-large",
            resource_id=large.id,
        )
        solution = self.solve_valid(
            replace(
                instance,
                equipment=equipment,
                steps=steps,
                capabilities=instance.capabilities + (capability,),
            )
        )
        self.assertTrue(
            all(
                item.loaded_quantity <= item.capacity
                for item in self.stage_loads(solution)
            )
        )

    def test_frozen_load_device_time_recipe_and_members_are_unchanged(self):
        instance = valid_instance()
        step = next(item for item in instance.steps if item.stage == "sintering")
        frozen_step = replace(
            step,
            frozen=True,
            assigned_resource_id="resource:sintering",
        )
        frozen = FrozenFurnaceLoad(
            id="furnace_load:FROZEN-1",
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
        )
        frozen_instance = replace(
            instance,
            steps=tuple(
                frozen_step if item.id == step.id else item for item in instance.steps
            ),
            frozen_furnace_loads=(frozen,),
        )
        solution = self.solve_valid(frozen_instance)
        load = next(
            item for item in solution.furnace_loads if item.load_id == frozen.id
        )
        self.assertTrue(load.frozen)
        self.assertEqual(load.equipment_id, frozen.resource_id)
        self.assertEqual(load.start_minute, frozen.start_minute)
        self.assertEqual(load.end_minute, frozen.end_minute)
        self.assertEqual(load.member_task_ids, frozen.member_task_ids)
        tampered = replace(
            solution,
            furnace_loads=tuple(
                (
                    replace(item, capacity=item.capacity + 1)
                    if item.load_id == frozen.id
                    else item
                )
                for item in solution.furnace_loads
            ),
        )
        report = SchedulingSolutionValidator().validate(frozen_instance, tampered)
        self.assertIn("MLCC-SV030", {item.code for item in report.violations})

    def test_multi_member_frozen_load_is_one_resource_interval(self):
        instance = two_batch_instance()
        members = tuple(
            sorted(
                (item for item in instance.steps if item.stage == "sintering"),
                key=lambda item: item.id,
            )
        )
        start = members[0].original_start_minute
        end = members[0].original_end_minute
        frozen_members = {
            item.id: replace(
                item,
                frozen=True,
                assigned_resource_id="resource:sintering",
                original_start_minute=start,
                original_end_minute=end,
            )
            for item in members
        }
        frozen = FrozenFurnaceLoad(
            id="furnace_load:FROZEN-MULTI",
            stage="sintering",
            resource_id="resource:sintering",
            recipe_id="recipe:sintering",
            furnace_program_key="SINTERING-V1",
            start_minute=start,
            end_minute=end,
            capacity=1000,
            loaded_quantity=2,
            load_unit="tray",
            member_task_ids=tuple(item.id for item in members),
            status="running",
        )
        solution = self.solve_valid(
            replace(
                instance,
                steps=tuple(
                    frozen_members.get(item.id, item) for item in instance.steps
                ),
                frozen_furnace_loads=(frozen,),
            )
        )
        load = next(
            item for item in solution.furnace_loads if item.load_id == frozen.id
        )
        self.assertEqual(load.member_task_ids, frozen.member_task_ids)
        self.assertTrue(load.frozen)
        self.assertEqual(load.loaded_quantity, 2)

    def test_maximum_wait_prevents_waiting_to_fill_furnace(self):
        instance = two_batch_instance()
        steps = tuple(
            (
                replace(item, maximum_wait_minutes=0)
                if item.stage in ("debinding", "sintering")
                else item
            )
            for item in instance.steps
        )
        solution = self.solve_valid(replace(instance, steps=steps))
        self.assertGreaterEqual(len(self.stage_loads(solution)), 2)

    def test_batch_over_all_candidate_capacities_returns_p017(self):
        instance = valid_instance()
        steps = tuple(
            (
                replace(
                    item,
                    load_requirements=(
                        replace(item.load_requirements[0], quantity=2000),
                    ),
                )
                if item.stage == "sintering"
                else item
            )
            for item in instance.steps
        )
        report = PlanningInstanceValidator().validate(replace(instance, steps=steps))
        target = next(item for item in report.issues if item.code == "MLCC-P017")
        self.assertEqual(target.severity, Severity.BLOCKER.value)

    def test_inexact_unit_conversion_returns_p020(self):
        instance = valid_instance()
        steps = tuple(
            (
                replace(
                    item,
                    load_requirements=(
                        FurnaceLoadRequirement(
                            resource_id="resource:sintering",
                            quantity=None,
                            load_unit="tray",
                            source_quantity=Decimal("5"),
                            source_unit="piece",
                        ),
                    ),
                )
                if item.stage == "sintering"
                else item
            )
            for item in instance.steps
        )
        report = PlanningInstanceValidator().validate(replace(instance, steps=steps))
        self.assertIn("MLCC-P020", {item.code for item in report.issues})

    def test_batching_never_worsens_phase3a_weighted_tardiness(self):
        solution = self.solve_valid(two_batch_instance())
        self.assertLessEqual(
            solution.phase3b_metrics["weighted_tardiness"],
            solution.phase3a_baseline_metrics["weighted_tardiness"],
        )
