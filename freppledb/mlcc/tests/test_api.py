from datetime import date

from django.db import connection
from django.test import TestCase
from django.urls import resolve
from rest_framework.test import APIRequestFactory, force_authenticate

from freppledb.common.models import User
from freppledb.mlcc.models import MlccRecipe
from freppledb.mlcc.serializers import (
    MlccBatchGenealogyAPI,
    MlccCompatibilityRuleAPI,
    MlccEquipmentCapabilityAPI,
    MlccFurnaceLoadAPI,
    MlccFurnaceLoadItemAPI,
    MlccFurnaceProgramAPI,
    MlccFurnaceStateSnapshotAPI,
    MlccFurnaceTransitionAPI,
    MlccFurnaceTransitionRuleAPI,
    MlccLoadUnitConversionAPI,
    MlccQualityHoldAPI,
    MlccRecipeAPI,
    MlccScheduleResultAPI,
    MlccScheduleRunAPI,
    MlccSetupMatrixAPI,
)

from .base import MlccTestDataMixin


class MlccAPITest(MlccTestDataMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        if connection.vendor == "sqlite":
            # The smoke suite doesn't implement PostgreSQL arrays/sequences.
            user = User(
                id=9001,
                username="mlccadmin",
                email="mlcc@example.com",
                is_superuser=True,
                is_active=False,
                databases=None,
            )
            user.set_password("admin")
            user._state.db = "default"
            user.save(force_insert=True)
            User.objects.filter(pk=user.pk).update(
                is_active=True, is_superuser=True, is_staff=True
            )
            with connection.cursor() as cursor:
                cursor.execute(
                    "update common_user set databases = %s where id = %s",
                    ["default", user.pk],
                )
        else:
            User.objects.create_superuser("mlccadmin", "mlcc@example.com", "admin")

    def setUp(self):
        self.factory = APIRequestFactory()
        self.user = User.objects.get(username="mlccadmin")

    def call_api(self, view, method="get", data=None, path="/api/mlcc/test/"):
        request = getattr(self.factory, method)(path, data=data, format="json")
        request.database = "default"
        request.prefix = ""
        force_authenticate(request, user=self.user)
        return view.as_view()(request)

    def test_recipe_list_and_create(self):
        response = self.call_api(MlccRecipeAPI)
        self.assertEqual(response.status_code, 200)
        response = self.call_api(
            MlccRecipeAPI,
            method="post",
            path="/api/mlcc/mlccrecipe/",
            data={
                "name": "Stacking recipe",
                "version": "V1",
                "effective_date": date.today().isoformat(),
                "process_stage": "stacking",
                "item": self.item.pk,
            },
        )
        self.assertIn(response.status_code, (200, 201))
        self.assertTrue(MlccRecipe.objects.filter(name="Stacking recipe").exists())

    def test_api_returns_validation_error(self):
        response = self.call_api(
            MlccFurnaceLoadAPI,
            method="post",
            path="/api/mlcc/mlccfurnaceload/",
            data={
                "reference": "INVALID-LOAD",
                "resource": self.resource.pk,
                "capacity": "0",
            },
        )
        self.assertEqual(response.status_code, 400)

    def test_all_list_endpoints(self):
        endpoints = (
            ("mlccrecipe", MlccRecipeAPI),
            ("mlccloadunitconversion", MlccLoadUnitConversionAPI),
            ("mlccequipmentcapability", MlccEquipmentCapabilityAPI),
            ("mlcccompatibilityrule", MlccCompatibilityRuleAPI),
            ("mlccsetupmatrix", MlccSetupMatrixAPI),
            ("mlccbatchgenealogy", MlccBatchGenealogyAPI),
            ("mlccfurnaceload", MlccFurnaceLoadAPI),
            ("mlccfurnaceloaditem", MlccFurnaceLoadItemAPI),
            ("mlccfurnaceprogram", MlccFurnaceProgramAPI),
            ("mlccfurnacestatesnapshot", MlccFurnaceStateSnapshotAPI),
            ("mlccfurnacetransitionrule", MlccFurnaceTransitionRuleAPI),
            ("mlccfurnacetransition", MlccFurnaceTransitionAPI),
            ("mlccqualityhold", MlccQualityHoldAPI),
            ("mlccschedulerun", MlccScheduleRunAPI),
            ("mlccscheduleresult", MlccScheduleResultAPI),
        )
        for endpoint, view in endpoints:
            with self.subTest(endpoint=endpoint):
                path = f"/api/mlcc/{endpoint}/"
                self.assertIsNotNone(resolve(path))
                response = self.call_api(view, path=path)
                self.assertEqual(response.status_code, 200)
