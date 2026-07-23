from django.core import management
from django.test import TestCase

from freppledb.input.models import Operation, Resource
from freppledb.mlcc.models import (
    MlccFurnaceLoad,
    MlccQualityHold,
    MlccRecipe,
    MlccScheduleResult,
)


class MlccDemoDataTest(TestCase):
    def test_demo_loader_is_idempotent_and_covers_five_stages(self):
        management.call_command("load_mlcc_demo", verbosity=0)
        management.call_command("load_mlcc_demo", verbosity=0)
        stages = {"stacking", "lamination", "cutting", "debinding", "sintering"}
        self.assertEqual(
            set(
                Operation.objects.filter(source="mlcc_demo").values_list(
                    "mlcc_process_stage", flat=True
                )
            ),
            stages,
        )
        self.assertEqual(Resource.objects.filter(source="mlcc_demo").count(), 5)
        self.assertEqual(MlccRecipe.objects.filter(source="mlcc_demo").count(), 6)
        self.assertEqual(MlccFurnaceLoad.objects.filter(source="mlcc_demo").count(), 1)
        self.assertEqual(MlccQualityHold.objects.filter(status="active").count(), 1)
        self.assertEqual(
            MlccScheduleResult.objects.filter(source="mlcc_demo").count(), 6
        )
