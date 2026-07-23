from datetime import date, timedelta
from decimal import Decimal

from django.utils import timezone

from freppledb.input.models import (
    Item,
    Location,
    ManufacturingOrder,
    Operation,
    Resource,
)
from freppledb.mlcc.models import MlccRecipe


class MlccTestDataMixin:
    @classmethod
    def setUpTestData(cls):
        cls.location = Location.objects.create(name="MLCC test plant")
        cls.item = Item.objects.create(name="MLCC test item", mlcc_product_family="X7R")
        cls.resource = Resource.objects.create(
            name="MLCC furnace",
            location=cls.location,
            mlcc_equipment_group="sintering",
            mlcc_is_furnace=True,
            mlcc_nominal_capacity=Decimal("100"),
        )
        cls.operation = Operation.objects.create(
            name="MLCC sintering",
            location=cls.location,
            item=cls.item,
            duration=timedelta(hours=8),
            mlcc_process_stage="sintering",
            mlcc_recipe_required=True,
            mlcc_batch_required=True,
        )
        now = timezone.now()
        cls.order = ManufacturingOrder.objects.create(
            reference="MLCC-MO-TEST",
            status="approved",
            operation=cls.operation,
            quantity=Decimal("10"),
            startdate=now,
            enddate=now + timedelta(hours=8),
            batch="MLCC-BATCH-TEST",
            mlcc_batch_code="MLCC-BATCH-TEST",
            mlcc_schedulable=True,
        )
        cls.recipe = MlccRecipe.objects.create(
            name="Sinter recipe",
            version="V1",
            effective_date=date.today(),
            process_stage="sintering",
            item=cls.item,
            operation=cls.operation,
        )
