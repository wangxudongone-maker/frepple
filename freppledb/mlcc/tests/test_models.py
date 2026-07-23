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
    MlccQualityHold,
    MlccRecipe,
    MlccScheduleResult,
    MlccScheduleRun,
)

from .base import MlccTestDataMixin


class MlccValidationTest(MlccTestDataMixin, TestCase):
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
