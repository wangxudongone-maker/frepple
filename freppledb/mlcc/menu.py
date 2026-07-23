from django.utils.translation import gettext_lazy as _

from freppledb.menu import menu

from .models import (
    MlccBatchGenealogy,
    MlccCompatibilityRule,
    MlccEquipmentCapability,
    MlccFurnaceLoad,
    MlccFurnaceLoadItem,
    MlccQualityHold,
    MlccRecipe,
    MlccScheduleResult,
    MlccScheduleRun,
    MlccSetupMatrix,
)
from .views import (
    MlccBatchGenealogyList,
    MlccCompatibilityRuleList,
    MlccEquipmentCapabilityList,
    MlccFurnaceLoadItemList,
    MlccFurnaceLoadList,
    MlccQualityHoldList,
    MlccRecipeList,
    MlccScheduleResultList,
    MlccScheduleRunList,
    MlccSetupMatrixList,
)

menu.addGroup("mlcc", label=_("MLCC planning"), index=250)

_items = (
    ("recipes", _("Recipes"), "mlccrecipe", MlccRecipeList, MlccRecipe, 100),
    (
        "capabilities",
        _("Equipment capabilities"),
        "mlccequipmentcapability",
        MlccEquipmentCapabilityList,
        MlccEquipmentCapability,
        110,
    ),
    (
        "compatibility",
        _("Compatibility rules"),
        "mlcccompatibilityrule",
        MlccCompatibilityRuleList,
        MlccCompatibilityRule,
        120,
    ),
    (
        "setups",
        _("Setup matrices"),
        "mlccsetupmatrix",
        MlccSetupMatrixList,
        MlccSetupMatrix,
        130,
    ),
    (
        "genealogy",
        _("Batch genealogy"),
        "mlccbatchgenealogy",
        MlccBatchGenealogyList,
        MlccBatchGenealogy,
        200,
    ),
    (
        "furnace-loads",
        _("Furnace loads"),
        "mlccfurnaceload",
        MlccFurnaceLoadList,
        MlccFurnaceLoad,
        210,
    ),
    (
        "furnace-items",
        _("Furnace load items"),
        "mlccfurnaceloaditem",
        MlccFurnaceLoadItemList,
        MlccFurnaceLoadItem,
        220,
    ),
    (
        "quality-holds",
        _("Quality holds"),
        "mlccqualityhold",
        MlccQualityHoldList,
        MlccQualityHold,
        230,
    ),
    (
        "schedule-runs",
        _("Schedule runs"),
        "mlccschedulerun",
        MlccScheduleRunList,
        MlccScheduleRun,
        300,
    ),
    (
        "schedule-results",
        _("Schedule results"),
        "mlccscheduleresult",
        MlccScheduleResultList,
        MlccScheduleResult,
        310,
    ),
)

for key, label, slug, report, model, index in _items:
    menu.addItem(
        "mlcc",
        key,
        label=label,
        url=f"/data/mlcc/{slug}/",
        report=report,
        model=model,
        index=index,
    )
