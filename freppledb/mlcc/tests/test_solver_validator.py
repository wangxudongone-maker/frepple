from dataclasses import replace
from decimal import Decimal

from django.test import SimpleTestCase

from freppledb.mlcc.solver.extractor import (
    operation_duration_minutes,
    timedelta_minutes,
)
from freppledb.mlcc.solver.schema import (
    CalendarInterval,
    CompatibilityRule,
    CustomerOrder,
    Equipment,
    EquipmentCapability,
    FrozenFurnaceLoad,
    FurnaceProgram,
    FurnaceLoadRequirement,
    FurnaceStateSnapshot,
    FurnaceTransitionRule,
    MaterialAvailability,
    PlanningInstance,
    PlanningWindow,
    ProcessStep,
    ProductionBatch,
    Recipe,
)
from freppledb.mlcc.solver.serializer import (
    planning_instance_fingerprint,
    planning_instance_json,
)
from freppledb.mlcc.solver.validator import PlanningInstanceValidator


def valid_instance():
    stages = ("stacking", "lamination", "cutting", "debinding", "sintering")
    steps = []
    equipment = []
    capabilities = []
    for sequence, stage in enumerate(stages, 1):
        task_id = f"task:{sequence}"
        resource_id = f"resource:{stage}"
        recipe_id = f"recipe:{stage}" if stage in ("debinding", "sintering") else None
        steps.append(
            ProcessStep(
                id=task_id,
                batch_id="batch:b1",
                sequence=sequence,
                stage=stage,
                operation_id=f"operation:{stage}",
                quantity=Decimal("100"),
                duration_minutes=60,
                minimum_batch=Decimal("1"),
                maximum_batch=Decimal("1000"),
                candidate_resource_ids=(resource_id,),
                certified_resource_ids=(resource_id,),
                recipe_id=recipe_id,
                predecessor_ids=((f"task:{sequence - 1}",) if sequence > 1 else ()),
                maximum_wait_minutes=120,
                required_material_ids=(("material:raw",) if sequence == 1 else ()),
                original_start_minute=3000 + sequence * 120,
                original_end_minute=3060 + sequence * 120,
                load_requirements=(
                    (
                        FurnaceLoadRequirement(
                            resource_id=resource_id,
                            quantity=1,
                            load_unit="tray",
                            source_quantity=Decimal("1"),
                            source_unit="tray",
                            conversion_id="identity",
                            conversion_numerator=1,
                            conversion_denominator=1,
                        ),
                    )
                    if stage in ("debinding", "sintering")
                    else ()
                ),
            )
        )
        equipment.append(
            Equipment(
                id=resource_id,
                resource_id=stage,
                capacity=Decimal("1000"),
                load_unit="tray" if stage in ("debinding", "sintering") else "panel",
                equipment_group=(
                    "furnace-group" if stage in ("debinding", "sintering") else None
                ),
                shifts=(CalendarInterval(0, 20160, "shift"),),
            )
        )
        capabilities.append(
            EquipmentCapability(
                id=f"capability:{stage}",
                resource_id=resource_id,
                stage=stage,
                recipe_id=recipe_id,
                item_id="item:finished",
                minimum_quantity=Decimal("1"),
                maximum_quantity=Decimal("1000"),
                enabled=True,
            )
        )
    return PlanningInstance(
        window=PlanningWindow(
            origin="2026-01-05T00:00:00+08:00",
            horizon_minutes=20160,
            freeze_minutes=2880,
            timezone="Asia/Shanghai",
        ),
        customer_orders=(
            CustomerOrder(
                id="order:o1",
                item_id="item:finished",
                batch_id="batch:b1",
                quantity=Decimal("100"),
                due_minute=10000,
                priority=1,
            ),
        ),
        batches=(
            ProductionBatch(
                id="batch:b1",
                order_id="order:o1",
                item_id="item:finished",
                product_family="X7R",
                quantity=Decimal("100"),
                due_minute=10000,
                priority=1,
                quality_hold=False,
                schedulable=True,
            ),
        ),
        steps=tuple(steps),
        equipment=tuple(equipment),
        capabilities=tuple(capabilities),
        recipes=(
            Recipe(
                id="recipe:debinding",
                name="debinding",
                version="V1",
                stage="debinding",
                effective_date="2025-01-01",
                expiry_date=None,
                active=True,
                setup_family="debinding-a",
                furnace_program_key="DEBINDING-V1",
                furnace_program_id="furnace_program:debinding-v1",
                compatibility_group="CERAMIC-A",
            ),
            Recipe(
                id="recipe:sintering",
                name="sintering",
                version="V1",
                stage="sintering",
                effective_date="2025-01-01",
                expiry_date=None,
                active=True,
                setup_family="sintering-a",
                furnace_program_key="SINTERING-V1",
                furnace_program_id="furnace_program:sintering-v1",
                compatibility_group="CERAMIC-A",
            ),
        ),
        furnace_programs=(
            FurnaceProgram(
                id="furnace_program:debinding-v1",
                program_key="DEBINDING-V1",
                version="V1",
                stage="debinding",
                atmosphere_key="N2",
                required_pre_state_key="debinding-idle",
                resulting_post_state_key="debinding-done",
                effective_date="2025-01-01",
                expiry_date=None,
                active=True,
            ),
            FurnaceProgram(
                id="furnace_program:sintering-v1",
                program_key="SINTERING-V1",
                version="V1",
                stage="sintering",
                atmosphere_key="AIR",
                required_pre_state_key="sintering-idle",
                resulting_post_state_key="sintering-done",
                effective_date="2025-01-01",
                expiry_date=None,
                active=True,
            ),
        ),
        furnace_state_snapshots=(
            FurnaceStateSnapshot(
                id="furnace_state:debinding",
                resource_id="resource:debinding",
                observed_minute=-60,
                state_key="debinding-idle",
                current_program_id=None,
                available_minute=0,
            ),
            FurnaceStateSnapshot(
                id="furnace_state:sintering",
                resource_id="resource:sintering",
                observed_minute=-60,
                state_key="sintering-idle",
                current_program_id=None,
                available_minute=0,
            ),
        ),
        furnace_transition_rules=(
            FurnaceTransitionRule(
                id="transition_rule:debinding-initial",
                resource_id="resource:debinding",
                equipment_group=None,
                stage="debinding",
                from_state_key="debinding-idle",
                to_program_id="furnace_program:debinding-v1",
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
            FurnaceTransitionRule(
                id="transition_rule:debinding-self",
                resource_id="resource:debinding",
                equipment_group=None,
                stage="debinding",
                from_state_key="debinding-done",
                to_program_id="furnace_program:debinding-v1",
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
            FurnaceTransitionRule(
                id="transition_rule:sintering-initial",
                resource_id="resource:sintering",
                equipment_group=None,
                stage="sintering",
                from_state_key="sintering-idle",
                to_program_id="furnace_program:sintering-v1",
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
            FurnaceTransitionRule(
                id="transition_rule:sintering-self",
                resource_id="resource:sintering",
                equipment_group=None,
                stage="sintering",
                from_state_key="sintering-done",
                to_program_id="furnace_program:sintering-v1",
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
        ),
        compatibility_rules=(
            CompatibilityRule(
                id="compatibility:valid",
                stage="sintering",
                family_a="C0G",
                family_b="X7R",
                rule_type="forbid",
                enabled=True,
            ),
            CompatibilityRule(
                id="compatibility:debinding-self",
                stage="debinding",
                family_a="X7R",
                family_b="X7R",
                rule_type="allow",
                enabled=True,
            ),
            CompatibilityRule(
                id="compatibility:sintering-self",
                stage="sintering",
                family_a="X7R",
                family_b="X7R",
                rule_type="allow",
                enabled=True,
            ),
        ),
        materials=(
            MaterialAvailability(
                id="material:raw",
                item_id="item:raw",
                batch_id=None,
                quantity=Decimal("1000"),
                available_minute=0,
                kind="raw_material",
            ),
        ),
    )


class SolverConversionTest(SimpleTestCase):
    def test_time_conversion_uses_integer_minutes(self):
        from datetime import timedelta

        self.assertEqual(timedelta_minutes(timedelta(seconds=61)), 2)
        self.assertEqual(
            operation_duration_minutes(
                timedelta(seconds=30), timedelta(seconds=15), Decimal("2")
            ),
            1,
        )

    def test_decimal_serialization_and_json_are_stable(self):
        instance = valid_instance()
        first = planning_instance_json(instance)
        second = planning_instance_json(instance)
        self.assertEqual(first, second)
        self.assertEqual(
            planning_instance_fingerprint(instance),
            planning_instance_fingerprint(instance),
        )
        self.assertIn('"quantity":"100"', first)
        self.assertNotIn('"quantity":100.0', first)


class SolverValidationRuleTest(SimpleTestCase):
    def setUp(self):
        self.validator = PlanningInstanceValidator()

    def codes(self, instance):
        return {item.code for item in self.validator.validate(instance).issues}

    def test_valid_fixture_has_no_blocker(self):
        report = self.validator.validate(valid_instance())
        self.assertEqual(report.blocker_count, 0)
        self.assertTrue(report.can_start_solver)

    def test_missing_routing(self):
        instance = valid_instance()
        self.assertIn(
            "MLCC-P001", self.codes(replace(instance, steps=instance.steps[:-1]))
        )

    def test_invalid_standard_time(self):
        instance = valid_instance()
        steps = (replace(instance.steps[0], duration_minutes=0),) + instance.steps[1:]
        self.assertIn("MLCC-P002", self.codes(replace(instance, steps=steps)))

    def test_no_available_resource(self):
        instance = valid_instance()
        steps = (
            replace(instance.steps[0], candidate_resource_ids=()),
        ) + instance.steps[1:]
        self.assertIn("MLCC-P003", self.codes(replace(instance, steps=steps)))

    def test_missing_or_out_of_range_capability(self):
        instance = valid_instance()
        capabilities = (
            replace(instance.capabilities[0], maximum_quantity=Decimal("10")),
        ) + instance.capabilities[1:]
        self.assertIn(
            "MLCC-P004", self.codes(replace(instance, capabilities=capabilities))
        )

    def test_missing_furnace_recipe(self):
        instance = valid_instance()
        steps = (
            instance.steps[:3]
            + (replace(instance.steps[3], recipe_id=None),)
            + instance.steps[4:]
        )
        self.assertIn("MLCC-P005", self.codes(replace(instance, steps=steps)))

    def test_invalid_recipe_period(self):
        instance = valid_instance()
        recipes = (
            replace(instance.recipes[0], expiry_date="2025-12-31"),
            instance.recipes[1],
        )
        self.assertIn("MLCC-P006", self.codes(replace(instance, recipes=recipes)))

    def test_invalid_furnace_capacity(self):
        instance = valid_instance()
        equipment = instance.equipment[:-1] + (
            replace(instance.equipment[-1], capacity=Decimal("0")),
        )
        self.assertIn("MLCC-P007", self.codes(replace(instance, equipment=equipment)))

    def test_invalid_batch_or_load_unit(self):
        instance = valid_instance()
        equipment = instance.equipment[:-1] + (
            replace(instance.equipment[-1], load_unit=""),
        )
        self.assertIn("MLCC-P008", self.codes(replace(instance, equipment=equipment)))

    def test_compatibility_conflict(self):
        instance = valid_instance()
        rules = instance.compatibility_rules + (
            replace(
                instance.compatibility_rules[0],
                id="compatibility:conflict",
                family_a="X7R",
                family_b="C0G",
                rule_type="allow",
            ),
        )
        self.assertIn(
            "MLCC-P009", self.codes(replace(instance, compatibility_rules=rules))
        )

    def test_dependency_cycle(self):
        instance = valid_instance()
        steps = (
            replace(instance.steps[0], predecessor_ids=("task:5",)),
        ) + instance.steps[1:]
        self.assertIn("MLCC-P010", self.codes(replace(instance, steps=steps)))

    def test_quality_hold_cannot_be_schedulable(self):
        instance = valid_instance()
        batches = (replace(instance.batches[0], quality_hold=True, schedulable=True),)
        self.assertIn("MLCC-P011", self.codes(replace(instance, batches=batches)))

    def test_frozen_task_cannot_overlap_downtime(self):
        instance = valid_instance()
        frozen = replace(
            instance.steps[-1],
            frozen=True,
            assigned_resource_id="resource:sintering",
        )
        steps = instance.steps[:-1] + (frozen,)
        equipment = instance.equipment[:-1] + (
            replace(
                instance.equipment[-1],
                downtimes=(CalendarInterval(3500, 4000, "downtime"),),
            ),
        )
        codes = self.codes(replace(instance, steps=steps, equipment=equipment))
        self.assertIn("MLCC-P012", codes)

    def test_material_availability_is_required(self):
        instance = valid_instance()
        self.assertIn("MLCC-P013", self.codes(replace(instance, materials=())))

    def test_quantities_must_balance(self):
        instance = valid_instance()
        steps = (replace(instance.steps[0], quantity=Decimal("99")),) + instance.steps[
            1:
        ]
        self.assertIn("MLCC-P014", self.codes(replace(instance, steps=steps)))

    def test_maximum_wait_must_cover_processing_interval(self):
        instance = valid_instance()
        steps = (
            instance.steps[:1]
            + (
                replace(
                    instance.steps[1],
                    minimum_wait_minutes=60,
                    maximum_wait_minutes=1,
                ),
            )
            + instance.steps[2:]
        )
        self.assertIn("MLCC-P015", self.codes(replace(instance, steps=steps)))

    def test_outside_horizon_is_warning_with_actionable_fields(self):
        instance = valid_instance()
        orders = (replace(instance.customer_orders[0], due_minute=30000),)
        report = self.validator.validate(replace(instance, customer_orders=orders))
        target = next(item for item in report.issues if item.code == "MLCC-P016")
        self.assertEqual(target.severity, "WARNING")
        self.assertTrue(target.reason)
        self.assertTrue(target.suggestion)
        self.assertTrue(target.source_field)

    def test_recipe_program_mapping_is_required(self):
        instance = valid_instance()
        recipes = (
            replace(instance.recipes[0], furnace_program_id=None),
            instance.recipes[1],
        )
        self.assertIn(
            "MLCC-P021",
            self.codes(replace(instance, recipes=recipes)),
        )

    def test_initial_furnace_state_is_required(self):
        instance = valid_instance()
        states = tuple(
            item
            for item in instance.furnace_state_snapshots
            if item.resource_id != "resource:sintering"
        )
        self.assertIn(
            "MLCC-P022",
            self.codes(replace(instance, furnace_state_snapshots=states)),
        )

    def test_transition_rule_conflict_is_blocker(self):
        instance = valid_instance()
        duplicate = replace(
            instance.furnace_transition_rules[0],
            id="transition_rule:duplicate",
        )
        self.assertIn(
            "MLCC-P023",
            self.codes(
                replace(
                    instance,
                    furnace_transition_rules=instance.furnace_transition_rules
                    + (duplicate,),
                )
            ),
        )

    def test_unreachable_program_is_blocker(self):
        instance = valid_instance()
        rules = tuple(
            replace(item, allowed=False) if item.stage == "sintering" else item
            for item in instance.furnace_transition_rules
        )
        self.assertIn(
            "MLCC-P024",
            self.codes(replace(instance, furnace_transition_rules=rules)),
        )

    def test_frozen_load_without_transition_is_blocker(self):
        instance = valid_instance()
        task = replace(
            instance.steps[-1],
            frozen=True,
            assigned_resource_id="resource:sintering",
        )
        frozen = FrozenFurnaceLoad(
            id="furnace_load:frozen",
            stage="sintering",
            resource_id="resource:sintering",
            recipe_id="recipe:sintering",
            furnace_program_key="SINTERING-V1",
            start_minute=task.original_start_minute,
            end_minute=task.original_end_minute,
            capacity=1000,
            loaded_quantity=1,
            load_unit="tray",
            member_task_ids=(task.id,),
            status="running",
            furnace_program_id="furnace_program:sintering-v1",
        )
        self.assertIn(
            "MLCC-P025",
            self.codes(
                replace(
                    instance,
                    steps=instance.steps[:-1] + (task,),
                    frozen_furnace_loads=(frozen,),
                )
            ),
        )
