from django.urls import path

from freppledb import mode

autodiscover = True

if mode != "ASGI":
    from . import serializers, views
    from .solver.api import (
        MlccPlanningInstanceAPI,
        MlccPrecheckAPI,
        MlccPrecheckResultAPI,
        MlccSolveAPI,
    )

    _routes = (
        (
            "mlccrecipe",
            views.MlccRecipeList,
            serializers.MlccRecipeAPI,
            serializers.MlccRecipeDetailAPI,
        ),
        (
            "mlccloadunitconversion",
            views.MlccLoadUnitConversionList,
            serializers.MlccLoadUnitConversionAPI,
            serializers.MlccLoadUnitConversionDetailAPI,
        ),
        (
            "mlccequipmentcapability",
            views.MlccEquipmentCapabilityList,
            serializers.MlccEquipmentCapabilityAPI,
            serializers.MlccEquipmentCapabilityDetailAPI,
        ),
        (
            "mlcccompatibilityrule",
            views.MlccCompatibilityRuleList,
            serializers.MlccCompatibilityRuleAPI,
            serializers.MlccCompatibilityRuleDetailAPI,
        ),
        (
            "mlccsetupmatrix",
            views.MlccSetupMatrixList,
            serializers.MlccSetupMatrixAPI,
            serializers.MlccSetupMatrixDetailAPI,
        ),
        (
            "mlccbatchgenealogy",
            views.MlccBatchGenealogyList,
            serializers.MlccBatchGenealogyAPI,
            serializers.MlccBatchGenealogyDetailAPI,
        ),
        (
            "mlccfurnaceload",
            views.MlccFurnaceLoadList,
            serializers.MlccFurnaceLoadAPI,
            serializers.MlccFurnaceLoadDetailAPI,
        ),
        (
            "mlccfurnaceloaditem",
            views.MlccFurnaceLoadItemList,
            serializers.MlccFurnaceLoadItemAPI,
            serializers.MlccFurnaceLoadItemDetailAPI,
        ),
        (
            "mlccqualityhold",
            views.MlccQualityHoldList,
            serializers.MlccQualityHoldAPI,
            serializers.MlccQualityHoldDetailAPI,
        ),
        (
            "mlccschedulerun",
            views.MlccScheduleRunList,
            serializers.MlccScheduleRunAPI,
            serializers.MlccScheduleRunDetailAPI,
        ),
        (
            "mlccscheduleresult",
            views.MlccScheduleResultList,
            serializers.MlccScheduleResultAPI,
            serializers.MlccScheduleResultDetailAPI,
        ),
    )

    urlpatterns = []
    for slug, report, list_api, detail_api in _routes:
        urlpatterns.extend(
            [
                path(
                    f"data/mlcc/{slug}/",
                    report.as_view(),
                    name=f"mlcc_{slug}_changelist",
                ),
                path(f"api/mlcc/{slug}/", list_api.as_view()),
                path(f"api/mlcc/{slug}/<int:pk>/", detail_api.as_view()),
            ]
        )
    urlpatterns.extend(
        [
            path(
                "data/mlcc/precheckrun/",
                views.MlccPrecheckRunList.as_view(),
                name="mlcc_precheckrun_changelist",
            ),
            path(
                "data/mlcc/precheck/",
                views.MlccPrecheckIssueList.as_view(),
                name="mlcc_precheck_changelist",
            ),
            path("api/mlcc/planning-instance/", MlccPlanningInstanceAPI.as_view()),
            path("api/mlcc/precheck/", MlccPrecheckAPI.as_view()),
            path(
                "api/mlcc/precheck/<int:pk>/",
                MlccPrecheckResultAPI.as_view(),
            ),
            path("api/mlcc/solve/", MlccSolveAPI.as_view()),
        ]
    )
else:
    urlpatterns = []
