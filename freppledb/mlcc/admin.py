from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from freppledb.admin import data_site
from freppledb.common.adminforms import MultiDBModelAdmin

from .models import (
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
    MlccPrecheckIssue,
    MlccPrecheckRun,
    MlccRecipe,
    MlccScheduleResult,
    MlccScheduleRun,
    MlccSetupMatrix,
)


class MlccModelAdmin(MultiDBModelAdmin):
    save_on_top = True
    exclude = ("lastmodified",)

    def get_tabs(self, request, obj=None):
        opts = self.model._meta
        return [
            {
                "name": "edit",
                "label": _("edit"),
                "view": f"admin:{opts.app_label}_{opts.model_name}_change",
                "permissions": f"{opts.app_label}.change_{opts.model_name}",
            },
            {
                "name": "messages",
                "label": _("messages"),
                "view": f"admin:{opts.app_label}_{opts.model_name}_comment",
            },
            {
                "name": "history",
                "label": _("History"),
                "view": f"admin:{opts.app_label}_{opts.model_name}_history",
            },
        ]

    @property
    def tabs(self):
        opts = self.model._meta
        return [
            {
                "name": "edit",
                "label": _("edit"),
                "view": f"admin:{opts.app_label}_{opts.model_name}_change",
                "permissions": f"{opts.app_label}.change_{opts.model_name}",
            },
            {
                "name": "messages",
                "label": _("messages"),
                "view": f"admin:{opts.app_label}_{opts.model_name}_comment",
            },
            {
                "name": "history",
                "label": _("History"),
                "view": f"admin:{opts.app_label}_{opts.model_name}_history",
            },
        ]


@admin.register(MlccRecipe, site=data_site)
class MlccRecipeAdmin(MlccModelAdmin):
    raw_id_fields = ("item", "operation", "furnace_program")
    fields = (
        "name",
        "version",
        "effective_date",
        "expiry_date",
        "process_stage",
        "item",
        "operation",
        "active",
        "furnace_program",
        "furnace_program_key",
        "compatibility_group",
        "parameters",
        "source",
    )


@admin.register(MlccFurnaceProgram, site=data_site)
class MlccFurnaceProgramAdmin(MlccModelAdmin):
    fields = (
        "id",
        "program_key",
        "version",
        "process_stage",
        "atmosphere_key",
        "required_pre_state_key",
        "resulting_post_state_key",
        "effective_date",
        "expiry_date",
        "active",
        "source",
    )


@admin.register(MlccFurnaceStateSnapshot, site=data_site)
class MlccFurnaceStateSnapshotAdmin(MlccModelAdmin):
    raw_id_fields = ("resource", "current_program")
    fields = (
        "resource",
        "observed_at",
        "state_key",
        "current_program",
        "available_at",
        "source",
    )


@admin.register(MlccFurnaceTransitionRule, site=data_site)
class MlccFurnaceTransitionRuleAdmin(MlccModelAdmin):
    raw_id_fields = ("resource", "to_program")
    fields = (
        "resource",
        "equipment_group",
        "process_stage",
        "from_state_key",
        "to_program",
        "transition_type",
        "duration",
        "setup_cost",
        "allowed",
        "enabled",
        "priority",
        "effective_date",
        "expiry_date",
        "source",
    )


@admin.register(MlccLoadUnitConversion, site=data_site)
class MlccLoadUnitConversionAdmin(MlccModelAdmin):
    raw_id_fields = ("item",)
    fields = (
        "item",
        "from_unit",
        "to_unit",
        "numerator",
        "denominator",
        "enabled",
        "source",
    )


@admin.register(MlccEquipmentCapability, site=data_site)
class MlccEquipmentCapabilityAdmin(MlccModelAdmin):
    raw_id_fields = ("resource", "recipe", "item")
    fields = (
        "resource",
        "process_stage",
        "recipe",
        "item",
        "minimum_quantity",
        "maximum_quantity",
        "enabled",
        "source",
    )


@admin.register(MlccCompatibilityRule, site=data_site)
class MlccCompatibilityRuleAdmin(MlccModelAdmin):
    fields = (
        "name",
        "process_stage",
        "family_a",
        "family_b",
        "rule_type",
        "reason",
        "enabled",
        "priority",
        "source",
    )


@admin.register(MlccSetupMatrix, site=data_site)
class MlccSetupMatrixAdmin(MlccModelAdmin):
    raw_id_fields = ("resource", "from_recipe", "to_recipe")
    fields = (
        "resource",
        "process_stage",
        "from_recipe",
        "to_recipe",
        "setup_time",
        "setup_cost",
        "source",
    )


@admin.register(MlccBatchGenealogy, site=data_site)
class MlccBatchGenealogyAdmin(MlccModelAdmin):
    fields = ("parent_batch", "child_batch", "process_stage", "quantity", "source")


@admin.register(MlccFurnaceLoad, site=data_site)
class MlccFurnaceLoadAdmin(MlccModelAdmin):
    raw_id_fields = ("run", "resource", "recipe", "furnace_program")
    fields = (
        "reference",
        "run",
        "resource",
        "recipe",
        "furnace_program",
        "operation_type",
        "furnace_program_key",
        "planned_start",
        "planned_end",
        "status",
        "capacity",
        "loaded_quantity",
        "load_unit",
        "frozen",
        "details",
        "source",
    )


@admin.register(MlccFurnaceTransition, site=data_site)
class MlccFurnaceTransitionAdmin(MlccModelAdmin):
    raw_id_fields = (
        "run",
        "resource",
        "predecessor_load",
        "successor_load",
        "transition_rule",
    )
    fields = (
        "run",
        "resource",
        "predecessor_load",
        "successor_load",
        "transition_rule",
        "transition_type",
        "planned_start",
        "planned_end",
        "status",
        "details",
        "source",
    )


@admin.register(MlccFurnaceLoadItem, site=data_site)
class MlccFurnaceLoadItemAdmin(MlccModelAdmin):
    raw_id_fields = ("furnace_load", "manufacturing_order")
    fields = (
        "furnace_load",
        "manufacturing_order",
        "batch_code",
        "quantity",
        "load_unit",
        "conversion_trace",
        "sequence",
        "source",
    )


@admin.register(MlccQualityHold, site=data_site)
class MlccQualityHoldAdmin(MlccModelAdmin):
    raw_id_fields = ("manufacturing_order",)
    fields = (
        "batch_code",
        "manufacturing_order",
        "hold_type",
        "reason",
        "status",
        "held_at",
        "released_at",
        "source",
    )


@admin.register(MlccScheduleRun, site=data_site)
class MlccScheduleRunAdmin(MlccModelAdmin):
    fields = (
        "name",
        "status",
        "horizon_start",
        "horizon_end",
        "requested_at",
        "started_at",
        "finished_at",
        "parameters",
        "message",
        "source",
    )


@admin.register(MlccScheduleResult, site=data_site)
class MlccScheduleResultAdmin(MlccModelAdmin):
    raw_id_fields = ("run", "manufacturing_order", "resource", "furnace_load")
    fields = (
        "run",
        "manufacturing_order",
        "resource",
        "furnace_load",
        "batch_code",
        "planned_start",
        "planned_end",
        "quantity",
        "status",
        "sequence",
        "score",
        "details",
        "source",
    )


@admin.register(MlccPrecheckRun, site=data_site)
class MlccPrecheckRunAdmin(MlccModelAdmin):
    readonly_fields = (
        "reference",
        "status",
        "horizon_start",
        "horizon_end",
        "freeze_minutes",
        "factory_timezone",
        "instance_hash",
        "order_count",
        "batch_count",
        "task_count",
        "equipment_count",
        "blocker_count",
        "warning_count",
        "info_count",
        "duration_ms",
        "parameters",
        "source",
    )


@admin.register(MlccPrecheckIssue, site=data_site)
class MlccPrecheckIssueAdmin(MlccModelAdmin):
    raw_id_fields = ("run",)
    readonly_fields = (
        "run",
        "sequence",
        "severity",
        "code",
        "object_type",
        "object_id",
        "reason",
        "suggestion",
        "source_field",
        "object_url",
        "source",
    )
