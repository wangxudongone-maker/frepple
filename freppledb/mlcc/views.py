from django.utils.translation import gettext_lazy as _

from freppledb.common.report import (
    GridFieldBool,
    GridFieldChoice,
    GridFieldDate,
    GridFieldDateTime,
    GridFieldDuration,
    GridFieldInteger,
    GridFieldJSON,
    GridFieldLastModified,
    GridFieldNumber,
    GridFieldText,
    GridReport,
)

from .models import (
    MlccBatchGenealogy,
    MlccCompatibilityRule,
    MlccEquipmentCapability,
    MlccFurnaceLoad,
    MlccFurnaceLoadItem,
    MlccQualityHold,
    MlccPrecheckIssue,
    MlccPrecheckRun,
    MlccRecipe,
    MlccScheduleResult,
    MlccScheduleRun,
    MlccSetupMatrix,
    PROCESS_STAGES,
)


def detail_id(role):
    return GridFieldInteger(
        "id",
        title=_("identifier"),
        key=True,
        formatter="detail",
        extra=f'"role":"mlcc/{role}"',
        initially_hidden=True,
    )


common_tail = (
    GridFieldText("source", title=_("source"), initially_hidden=True),
    GridFieldLastModified("lastmodified"),
)


class MlccRecipeList(GridReport):
    title = _("MLCC recipes")
    model = MlccRecipe
    basequeryset = MlccRecipe.objects.all()
    frozenColumns = 1
    rows = (
        detail_id("mlccrecipe"),
        GridFieldText("name", title=_("recipe")),
        GridFieldText("version", title=_("version")),
        GridFieldDate("effective_date", title=_("effective date")),
        GridFieldDate("expiry_date", title=_("expiry date")),
        GridFieldChoice(
            "process_stage", title=_("process stage"), choices=PROCESS_STAGES
        ),
        GridFieldText(
            "item",
            title=_("item"),
            field_name="item__name",
            formatter="detail",
            extra='"role":"input/item"',
        ),
        GridFieldText(
            "operation",
            title=_("operation"),
            field_name="operation__name",
            formatter="detail",
            extra='"role":"input/operation"',
        ),
        GridFieldBool("active", title=_("active")),
        GridFieldJSON("parameters", title=_("parameters")),
    ) + common_tail


class MlccEquipmentCapabilityList(GridReport):
    title = _("MLCC equipment capabilities")
    model = MlccEquipmentCapability
    basequeryset = MlccEquipmentCapability.objects.all()
    frozenColumns = 1
    rows = (
        detail_id("mlccequipmentcapability"),
        GridFieldText(
            "resource",
            title=_("resource"),
            field_name="resource__name",
            formatter="detail",
            extra='"role":"input/resource"',
        ),
        GridFieldChoice(
            "process_stage", title=_("process stage"), choices=PROCESS_STAGES
        ),
        GridFieldText("recipe", title=_("recipe"), field_name="recipe__name"),
        GridFieldText("item", title=_("item"), field_name="item__name"),
        GridFieldNumber("minimum_quantity", title=_("minimum quantity")),
        GridFieldNumber("maximum_quantity", title=_("maximum quantity")),
        GridFieldBool("enabled", title=_("enabled")),
    ) + common_tail


class MlccCompatibilityRuleList(GridReport):
    title = _("MLCC compatibility rules")
    model = MlccCompatibilityRule
    basequeryset = MlccCompatibilityRule.objects.all()
    frozenColumns = 1
    rows = (
        detail_id("mlcccompatibilityrule"),
        GridFieldText("name", title=_("name")),
        GridFieldChoice(
            "process_stage", title=_("process stage"), choices=PROCESS_STAGES
        ),
        GridFieldText("family_a", title=_("product family A")),
        GridFieldText("family_b", title=_("product family B")),
        GridFieldChoice(
            "rule_type", title=_("rule type"), choices=MlccCompatibilityRule.RULE_TYPES
        ),
        GridFieldText("reason", title=_("reason")),
        GridFieldBool("enabled", title=_("enabled")),
        GridFieldInteger("priority", title=_("priority")),
    ) + common_tail


class MlccSetupMatrixList(GridReport):
    title = _("MLCC setup matrices")
    model = MlccSetupMatrix
    basequeryset = MlccSetupMatrix.objects.all()
    frozenColumns = 1
    rows = (
        detail_id("mlccsetupmatrix"),
        GridFieldText("resource", title=_("resource"), field_name="resource__name"),
        GridFieldChoice(
            "process_stage", title=_("process stage"), choices=PROCESS_STAGES
        ),
        GridFieldText(
            "from_recipe", title=_("from recipe"), field_name="from_recipe__name"
        ),
        GridFieldText("to_recipe", title=_("to recipe"), field_name="to_recipe__name"),
        GridFieldDuration("setup_time", title=_("setup time")),
        GridFieldNumber("setup_cost", title=_("setup cost")),
    ) + common_tail


class MlccBatchGenealogyList(GridReport):
    title = _("MLCC batch genealogies")
    model = MlccBatchGenealogy
    basequeryset = MlccBatchGenealogy.objects.all()
    frozenColumns = 1
    rows = (
        detail_id("mlccbatchgenealogy"),
        GridFieldText("parent_batch", title=_("parent batch")),
        GridFieldText("child_batch", title=_("child batch")),
        GridFieldChoice(
            "process_stage", title=_("process stage"), choices=PROCESS_STAGES
        ),
        GridFieldNumber("quantity", title=_("quantity")),
    ) + common_tail


class MlccFurnaceLoadList(GridReport):
    title = _("MLCC furnace loads")
    model = MlccFurnaceLoad
    basequeryset = MlccFurnaceLoad.objects.all()
    frozenColumns = 1
    rows = (
        detail_id("mlccfurnaceload"),
        GridFieldText("reference", title=_("reference")),
        GridFieldText("resource", title=_("resource"), field_name="resource__name"),
        GridFieldText("recipe", title=_("recipe"), field_name="recipe__name"),
        GridFieldDateTime("planned_start", title=_("planned start")),
        GridFieldDateTime("planned_end", title=_("planned end")),
        GridFieldChoice("status", title=_("status"), choices=MlccFurnaceLoad.STATUSES),
        GridFieldNumber("capacity", title=_("capacity")),
    ) + common_tail


class MlccFurnaceLoadItemList(GridReport):
    title = _("MLCC furnace load items")
    model = MlccFurnaceLoadItem
    basequeryset = MlccFurnaceLoadItem.objects.all()
    frozenColumns = 1
    rows = (
        detail_id("mlccfurnaceloaditem"),
        GridFieldText(
            "furnace_load",
            title=_("furnace load"),
            field_name="furnace_load__reference",
        ),
        GridFieldText(
            "manufacturing_order",
            title=_("manufacturing order"),
            field_name="manufacturing_order__reference",
        ),
        GridFieldText("batch_code", title=_("batch code")),
        GridFieldNumber("quantity", title=_("quantity")),
        GridFieldInteger("sequence", title=_("sequence")),
    ) + common_tail


class MlccQualityHoldList(GridReport):
    title = _("MLCC quality holds")
    model = MlccQualityHold
    basequeryset = MlccQualityHold.objects.all()
    frozenColumns = 1
    rows = (
        detail_id("mlccqualityhold"),
        GridFieldText("batch_code", title=_("batch code")),
        GridFieldText(
            "manufacturing_order",
            title=_("manufacturing order"),
            field_name="manufacturing_order__reference",
        ),
        GridFieldText("hold_type", title=_("hold type")),
        GridFieldText("reason", title=_("reason")),
        GridFieldChoice("status", title=_("status"), choices=MlccQualityHold.STATUSES),
        GridFieldDateTime("held_at", title=_("held at")),
        GridFieldDateTime("released_at", title=_("released at")),
    ) + common_tail


class MlccScheduleRunList(GridReport):
    title = _("MLCC schedule runs")
    model = MlccScheduleRun
    basequeryset = MlccScheduleRun.objects.all()
    frozenColumns = 1
    rows = (
        detail_id("mlccschedulerun"),
        GridFieldText("name", title=_("name")),
        GridFieldChoice("status", title=_("status"), choices=MlccScheduleRun.STATUSES),
        GridFieldDateTime("horizon_start", title=_("horizon start")),
        GridFieldDateTime("horizon_end", title=_("horizon end")),
        GridFieldDateTime("requested_at", title=_("requested at")),
        GridFieldDateTime("started_at", title=_("started at")),
        GridFieldDateTime("finished_at", title=_("finished at")),
        GridFieldJSON("parameters", title=_("parameters")),
        GridFieldText("message", title=_("message")),
    ) + common_tail


class MlccScheduleResultList(GridReport):
    title = _("MLCC schedule results")
    model = MlccScheduleResult
    basequeryset = MlccScheduleResult.objects.all()
    frozenColumns = 1
    rows = (
        detail_id("mlccscheduleresult"),
        GridFieldText("run", title=_("schedule run"), field_name="run__name"),
        GridFieldText(
            "manufacturing_order",
            title=_("manufacturing order"),
            field_name="manufacturing_order__reference",
        ),
        GridFieldText("resource", title=_("resource"), field_name="resource__name"),
        GridFieldText(
            "furnace_load",
            title=_("furnace load"),
            field_name="furnace_load__reference",
        ),
        GridFieldText("batch_code", title=_("batch code")),
        GridFieldDateTime("planned_start", title=_("planned start")),
        GridFieldDateTime("planned_end", title=_("planned end")),
        GridFieldNumber("quantity", title=_("quantity")),
        GridFieldChoice(
            "status", title=_("status"), choices=MlccScheduleResult.STATUSES
        ),
        GridFieldInteger("sequence", title=_("sequence")),
        GridFieldNumber("score", title=_("score")),
        GridFieldJSON("details", title=_("details")),
    ) + common_tail


class MlccPrecheckRunList(GridReport):
    title = _("MLCC precheck runs")
    model = MlccPrecheckRun
    basequeryset = MlccPrecheckRun.objects.all()
    frozenColumns = 1
    rows = (
        detail_id("mlccprecheckrun"),
        GridFieldText("reference", title=_("reference")),
        GridFieldChoice("status", title=_("status"), choices=MlccPrecheckRun.STATUSES),
        GridFieldDateTime("horizon_start", title=_("horizon start")),
        GridFieldDateTime("horizon_end", title=_("horizon end")),
        GridFieldInteger("freeze_minutes", title=_("freeze minutes")),
        GridFieldText("factory_timezone", title=_("factory timezone")),
        GridFieldText("instance_hash", title=_("instance hash")),
        GridFieldInteger("order_count", title=_("order count")),
        GridFieldInteger("batch_count", title=_("batch count")),
        GridFieldInteger("task_count", title=_("task count")),
        GridFieldInteger("equipment_count", title=_("equipment count")),
        GridFieldInteger("blocker_count", title=_("blocker count")),
        GridFieldInteger("warning_count", title=_("warning count")),
        GridFieldInteger("info_count", title=_("info count")),
        GridFieldInteger("duration_ms", title=_("duration milliseconds")),
    ) + common_tail


class MlccPrecheckIssueList(GridReport):
    title = _("MLCC planning data check")
    model = MlccPrecheckIssue
    basequeryset = MlccPrecheckIssue.objects.select_related("run").all()
    frozenColumns = 1
    rows = (
        detail_id("mlccprecheckissue"),
        GridFieldText("run", title=_("precheck run"), field_name="run__reference"),
        GridFieldChoice(
            "severity", title=_("severity"), choices=MlccPrecheckIssue.SEVERITIES
        ),
        GridFieldText("code", title=_("error code")),
        GridFieldText("object_type", title=_("object type")),
        GridFieldText("object_id", title=_("object identifier")),
        GridFieldText("reason", title=_("reason")),
        GridFieldText("suggestion", title=_("suggestion")),
        GridFieldText("source_field", title=_("source field")),
        GridFieldText(
            "object_url",
            title=_("locate source data"),
            formatter="link",
            extra='"formatoptions":{"target":"_self"}',
            editable=False,
        ),
        GridFieldInteger(
            "order_count", title=_("order count"), field_name="run__order_count"
        ),
        GridFieldInteger(
            "batch_count", title=_("batch count"), field_name="run__batch_count"
        ),
        GridFieldInteger(
            "task_count", title=_("task count"), field_name="run__task_count"
        ),
        GridFieldInteger(
            "equipment_count",
            title=_("equipment count"),
            field_name="run__equipment_count",
        ),
        GridFieldInteger(
            "blocker_count", title=_("blocker count"), field_name="run__blocker_count"
        ),
        GridFieldInteger(
            "warning_count", title=_("warning count"), field_name="run__warning_count"
        ),
    ) + common_tail
