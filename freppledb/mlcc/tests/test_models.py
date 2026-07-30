from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from freppledb.mlcc.models import (
    MlccBatchGenealogy,
    MlccCompatibilityRule,
    MlccEquipmentCapability,
    MlccFurnaceLoad,
    MlccFurnaceLoadItem,
    MlccFurnaceProgram,
    MlccFurnaceStateSnapshot,
    MlccFurnaceTransition,
    MlccFurnaceTransitionRule,
    MlccLoadUnitConversion,
    MlccQualityHold,
    MlccRecipe,
    MlccScheduleResult,
    MlccScheduleRun,
)

from .base import MlccTestDataMixin


class MlccValidationTest(MlccTestDataMixin, TestCase):
    def furnace_program(self, identifier="program:test", version="V1"):
        return MlccFurnaceProgram.objects.create(
            id=identifier,
            program_key=identifier.upper(),
            version=version,
            process_stage="sintering",
            atmosphere_key="AIR",
            required_pre_state_key="idle",
            resulting_post_state_key=f"done:{version}",
            effective_date=date(2025, 1, 1),
        )

    def test_recipe_requires_version_and_effective_date(self):
        with self.assertRaises(ValidationError):
            MlccRecipe(
                name="invalid",
                version="",
                effective_date=None,
                process_stage="stacking",
            ).save()

    def test_furnace_capacity_must_be_positive(self):
        with self.assertRaises(ValidationError):
            MlccFurnaceLoad(
                reference="LOAD-INVALID", resource=self.resource, capacity=Decimal("0")
            ).save()

    def test_equipment_capability_cannot_repeat(self):
        MlccEquipmentCapability.objects.create(
            resource=self.resource,
            process_stage="sintering",
            recipe=self.recipe,
            item=self.item,
        )
        with self.assertRaises(ValidationError):
            MlccEquipmentCapability.objects.create(
                resource=self.resource,
                process_stage="sintering",
                recipe=self.recipe,
                item=self.item,
            )

    def test_compatibility_rule_cannot_contradict(self):
        MlccCompatibilityRule.objects.create(
            name="allow A B",
            process_stage="sintering",
            family_a="A",
            family_b="B",
            rule_type="allow",
        )
        with self.assertRaises(ValidationError):
            MlccCompatibilityRule.objects.create(
                name="forbid B A",
                process_stage="sintering",
                family_a="B",
                family_b="A",
                rule_type="forbid",
            )
        with self.assertRaises(ValidationError):
            MlccCompatibilityRule.objects.create(
                name="self contradiction",
                process_stage="sintering",
                family_a="X7R",
                family_b="X7R",
                rule_type="forbid",
            )

    def test_batch_genealogy_rejects_cycles(self):
        MlccBatchGenealogy.objects.create(
            parent_batch="A", child_batch="B", process_stage="lamination"
        )
        MlccBatchGenealogy.objects.create(
            parent_batch="B", child_batch="C", process_stage="cutting"
        )
        with self.assertRaises(ValidationError):
            MlccBatchGenealogy.objects.create(
                parent_batch="C", child_batch="A", process_stage="sintering"
            )

    def test_quality_hold_blocks_schedulable_states(self):
        MlccQualityHold.objects.create(
            batch_code="MLCC-BATCH-TEST",
            manufacturing_order=self.order,
            reason="inspection pending",
        )
        self.order.refresh_from_db()
        self.assertFalse(self.order.mlcc_schedulable)
        load = MlccFurnaceLoad.objects.create(
            reference="LOAD-001", resource=self.resource, capacity=Decimal("100")
        )
        with self.assertRaises(ValidationError):
            MlccFurnaceLoadItem.objects.create(
                furnace_load=load,
                manufacturing_order=self.order,
                batch_code="MLCC-BATCH-TEST",
                quantity=Decimal("10"),
            )
        now = timezone.now()
        run = MlccScheduleRun.objects.create(
            name="RUN-001",
            horizon_start=now,
            horizon_end=now + timedelta(days=1),
        )
        with self.assertRaises(ValidationError):
            MlccScheduleResult.objects.create(
                run=run,
                manufacturing_order=self.order,
                resource=self.resource,
                batch_code="MLCC-BATCH-TEST",
                quantity=Decimal("10"),
                status="scheduled",
            )
        self.order.mlcc_schedulable = True
        with self.assertRaises(ValidationError):
            self.order.save()

    def test_furnace_items_cannot_exceed_capacity(self):
        load = MlccFurnaceLoad.objects.create(
            reference="LOAD-002", resource=self.resource, capacity=Decimal("5")
        )
        with self.assertRaises(ValidationError):
            MlccFurnaceLoadItem.objects.create(
                furnace_load=load,
                manufacturing_order=self.order,
                batch_code="MLCC-BATCH-TEST",
                quantity=Decimal("6"),
            )

    def test_load_conversion_requires_an_exact_positive_ratio(self):
        with self.assertRaises(ValidationError):
            MlccLoadUnitConversion.objects.create(
                item=self.item,
                from_unit="piece",
                to_unit="tray",
                numerator=0,
                denominator=1,
            )
        with self.assertRaises(ValidationError):
            MlccLoadUnitConversion.objects.create(
                item=self.item,
                from_unit="tray",
                to_unit="tray",
                numerator=1,
                denominator=2,
            )

    def test_proposed_furnace_load_requires_schedule_run(self):
        with self.assertRaises(ValidationError):
            MlccFurnaceLoad.objects.create(
                reference="LOAD-PROPOSED-NO-RUN",
                resource=self.resource,
                capacity=Decimal("5"),
                loaded_quantity=Decimal("3"),
                load_unit="tray",
                status="proposed",
            )
        now = timezone.now()
        run = MlccScheduleRun.objects.create(
            name="RUN-PROPOSED",
            horizon_start=now,
            horizon_end=now + timedelta(days=1),
        )
        load = MlccFurnaceLoad.objects.create(
            reference="LOAD-PROPOSED",
            run=run,
            resource=self.resource,
            capacity=Decimal("5"),
            loaded_quantity=Decimal("3"),
            load_unit="tray",
            status="proposed",
        )
        self.assertEqual(load.run_id, run.pk)

    def test_recipe_program_mapping_must_use_same_stage_and_key(self):
        program = self.furnace_program()
        with self.assertRaises(ValidationError):
            MlccRecipe.objects.create(
                name="MISMATCHED-PROGRAM",
                version="V1",
                effective_date=date(2025, 1, 1),
                process_stage="debinding",
                furnace_program=program,
                furnace_program_key=program.program_key,
            )
        with self.assertRaises(ValidationError):
            MlccRecipe.objects.create(
                name="MISMATCHED-KEY",
                version="V1",
                effective_date=date(2025, 1, 1),
                process_stage="sintering",
                furnace_program=program,
                furnace_program_key="OTHER",
            )

    def test_state_and_transition_rules_are_explicit_and_unambiguous(self):
        program = self.furnace_program()
        now = timezone.now()
        with self.assertRaises(ValidationError):
            MlccFurnaceStateSnapshot.objects.create(
                resource=self.resource,
                observed_at=now,
                state_key="idle",
                available_at=now - timedelta(minutes=1),
            )
        MlccFurnaceTransitionRule.objects.create(
            resource=self.resource,
            process_stage="sintering",
            from_state_key="idle",
            to_program=program,
            transition_type="none",
            duration=timedelta(0),
            setup_cost=Decimal("0"),
            effective_date=date(2025, 1, 1),
        )
        lower_precedence = MlccFurnaceTransitionRule.objects.create(
            resource=self.resource,
            process_stage="sintering",
            from_state_key="idle",
            to_program=program,
            transition_type="cleaning",
            duration=timedelta(minutes=5),
            setup_cost=Decimal("1"),
            priority=10,
            effective_date=date(2025, 1, 1),
        )
        self.assertEqual(lower_precedence.priority, 10)
        with self.assertRaises(ValidationError):
            MlccFurnaceTransitionRule.objects.create(
                resource=self.resource,
                process_stage="sintering",
                from_state_key="idle",
                to_program=program,
                transition_type="cleaning",
                duration=timedelta(minutes=1),
                setup_cost=Decimal("1"),
                effective_date=date(2025, 1, 1),
            )

    def test_persisted_transition_status_is_preview_only(self):
        program = self.furnace_program()
        rule = MlccFurnaceTransitionRule.objects.create(
            resource=self.resource,
            process_stage="sintering",
            from_state_key="idle",
            to_program=program,
            transition_type="none",
            duration=timedelta(0),
            effective_date=date(2025, 1, 1),
        )
        now = timezone.now()
        run = MlccScheduleRun.objects.create(
            name="RUN-TRANSITION",
            horizon_start=now,
            horizon_end=now + timedelta(days=1),
        )
        load = MlccFurnaceLoad.objects.create(
            reference="LOAD-TRANSITION",
            run=run,
            resource=self.resource,
            furnace_program=program,
            operation_type="sintering",
            furnace_program_key=program.program_key,
            planned_start=now + timedelta(hours=1),
            planned_end=now + timedelta(hours=2),
            capacity=Decimal("5"),
            loaded_quantity=Decimal("1"),
            load_unit="tray",
            status="proposed",
        )
        with self.assertRaises(ValidationError):
            MlccFurnaceTransition.objects.create(
                run=run,
                resource=self.resource,
                successor_load=load,
                transition_rule=rule,
                transition_type="none",
                planned_start=load.planned_start,
                planned_end=load.planned_start,
                status="complete",
            )
