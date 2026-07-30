from django.core.exceptions import ValidationError as DjangoValidationError
from django_filters import rest_framework as filters
from rest_framework.exceptions import ValidationError
from rest_framework_bulk.drf3.serializers import BulkListSerializer, BulkSerializerMixin

from freppledb.common.api.serializers import ModelSerializer
from freppledb.common.api.views import (
    frePPleListCreateAPIView,
    frePPleRetrieveUpdateDestroyAPIView,
)

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
    MlccRecipe,
    MlccScheduleResult,
    MlccScheduleRun,
    MlccSetupMatrix,
)


def _as_api_validation_error(exc):
    if hasattr(exc, "message_dict"):
        return ValidationError(exc.message_dict)
    return ValidationError(exc.messages)


class MlccModelSerializer(BulkSerializerMixin, ModelSerializer):
    def create(self, validated_data):
        try:
            return super().create(validated_data)
        except DjangoValidationError as exc:
            raise _as_api_validation_error(exc)

    def update(self, instance, validated_data):
        try:
            return super().update(instance, validated_data)
        except DjangoValidationError as exc:
            raise _as_api_validation_error(exc)


class MlccRecipeFilter(filters.FilterSet):
    class Meta:
        model = MlccRecipe
        fields = {
            "name": ["exact", "in", "contains"],
            "version": ["exact", "in", "contains"],
            "effective_date": ["exact", "gt", "gte", "lt", "lte"],
            "process_stage": ["exact", "in"],
            "item": ["exact", "in"],
            "operation": ["exact", "in"],
            "active": ["exact"],
        }


class MlccRecipeSerializer(MlccModelSerializer):
    class Meta:
        model = MlccRecipe
        fields = "__all__"
        read_only_fields = ("lastmodified",)
        list_serializer_class = BulkListSerializer
        update_lookup_field = "id"
        partial = True


class MlccFurnaceProgramFilter(filters.FilterSet):
    class Meta:
        model = MlccFurnaceProgram
        fields = {
            "id": ["exact", "in", "contains"],
            "program_key": ["exact", "in", "contains"],
            "version": ["exact", "in"],
            "process_stage": ["exact", "in"],
            "atmosphere_key": ["exact", "in"],
            "active": ["exact"],
        }


class MlccFurnaceProgramSerializer(MlccModelSerializer):
    class Meta:
        model = MlccFurnaceProgram
        fields = "__all__"
        read_only_fields = ("lastmodified",)
        list_serializer_class = BulkListSerializer
        update_lookup_field = "id"
        partial = True


class MlccFurnaceStateSnapshotFilter(filters.FilterSet):
    class Meta:
        model = MlccFurnaceStateSnapshot
        fields = {
            "resource": ["exact", "in"],
            "state_key": ["exact", "in"],
            "current_program": ["exact", "in"],
            "observed_at": ["exact", "gt", "gte", "lt", "lte"],
            "available_at": ["exact", "gt", "gte", "lt", "lte"],
        }


class MlccFurnaceStateSnapshotSerializer(MlccModelSerializer):
    class Meta:
        model = MlccFurnaceStateSnapshot
        fields = "__all__"
        read_only_fields = ("lastmodified",)
        list_serializer_class = BulkListSerializer
        update_lookup_field = "id"
        partial = True


class MlccFurnaceTransitionRuleFilter(filters.FilterSet):
    class Meta:
        model = MlccFurnaceTransitionRule
        fields = {
            "resource": ["exact", "in"],
            "equipment_group": ["exact", "in"],
            "process_stage": ["exact", "in"],
            "from_state_key": ["exact", "in"],
            "to_program": ["exact", "in"],
            "transition_type": ["exact", "in"],
            "allowed": ["exact"],
            "enabled": ["exact"],
        }


class MlccFurnaceTransitionRuleSerializer(MlccModelSerializer):
    class Meta:
        model = MlccFurnaceTransitionRule
        fields = "__all__"
        read_only_fields = ("lastmodified",)
        list_serializer_class = BulkListSerializer
        update_lookup_field = "id"
        partial = True


class MlccLoadUnitConversionFilter(filters.FilterSet):
    class Meta:
        model = MlccLoadUnitConversion
        fields = {
            "item": ["exact", "in"],
            "from_unit": ["exact", "in"],
            "to_unit": ["exact", "in"],
            "enabled": ["exact"],
        }


class MlccLoadUnitConversionSerializer(MlccModelSerializer):
    class Meta:
        model = MlccLoadUnitConversion
        fields = "__all__"
        read_only_fields = ("lastmodified",)
        list_serializer_class = BulkListSerializer
        update_lookup_field = "id"
        partial = True


class MlccEquipmentCapabilityFilter(filters.FilterSet):
    class Meta:
        model = MlccEquipmentCapability
        fields = {
            "resource": ["exact", "in"],
            "process_stage": ["exact", "in"],
            "recipe": ["exact", "in"],
            "item": ["exact", "in"],
            "enabled": ["exact"],
        }


class MlccEquipmentCapabilitySerializer(MlccModelSerializer):
    class Meta:
        model = MlccEquipmentCapability
        fields = "__all__"
        read_only_fields = ("lastmodified",)
        list_serializer_class = BulkListSerializer
        update_lookup_field = "id"
        partial = True


class MlccCompatibilityRuleFilter(filters.FilterSet):
    class Meta:
        model = MlccCompatibilityRule
        fields = {
            "name": ["exact", "in", "contains"],
            "process_stage": ["exact", "in"],
            "family_a": ["exact", "in", "contains"],
            "family_b": ["exact", "in", "contains"],
            "rule_type": ["exact", "in"],
            "enabled": ["exact"],
        }


class MlccCompatibilityRuleSerializer(MlccModelSerializer):
    class Meta:
        model = MlccCompatibilityRule
        fields = "__all__"
        read_only_fields = ("lastmodified",)
        list_serializer_class = BulkListSerializer
        update_lookup_field = "id"
        partial = True


class MlccSetupMatrixFilter(filters.FilterSet):
    class Meta:
        model = MlccSetupMatrix
        fields = {
            "resource": ["exact", "in"],
            "process_stage": ["exact", "in"],
            "from_recipe": ["exact", "in"],
            "to_recipe": ["exact", "in"],
        }


class MlccSetupMatrixSerializer(MlccModelSerializer):
    class Meta:
        model = MlccSetupMatrix
        fields = "__all__"
        read_only_fields = ("lastmodified",)
        list_serializer_class = BulkListSerializer
        update_lookup_field = "id"
        partial = True


class MlccBatchGenealogyFilter(filters.FilterSet):
    class Meta:
        model = MlccBatchGenealogy
        fields = {
            "parent_batch": ["exact", "in", "contains"],
            "child_batch": ["exact", "in", "contains"],
            "process_stage": ["exact", "in"],
        }


class MlccBatchGenealogySerializer(MlccModelSerializer):
    class Meta:
        model = MlccBatchGenealogy
        fields = "__all__"
        read_only_fields = ("lastmodified",)
        list_serializer_class = BulkListSerializer
        update_lookup_field = "id"
        partial = True


class MlccFurnaceLoadFilter(filters.FilterSet):
    class Meta:
        model = MlccFurnaceLoad
        fields = {
            "reference": ["exact", "in", "contains"],
            "resource": ["exact", "in"],
            "recipe": ["exact", "in"],
            "status": ["exact", "in"],
            "planned_start": ["exact", "gt", "gte", "lt", "lte"],
        }


class MlccFurnaceLoadSerializer(MlccModelSerializer):
    class Meta:
        model = MlccFurnaceLoad
        fields = "__all__"
        read_only_fields = ("lastmodified",)
        list_serializer_class = BulkListSerializer
        update_lookup_field = "id"
        partial = True


class MlccFurnaceLoadItemFilter(filters.FilterSet):
    class Meta:
        model = MlccFurnaceLoadItem
        fields = {
            "furnace_load": ["exact", "in"],
            "manufacturing_order": ["exact", "in"],
            "batch_code": ["exact", "in", "contains"],
        }


class MlccFurnaceLoadItemSerializer(MlccModelSerializer):
    class Meta:
        model = MlccFurnaceLoadItem
        fields = "__all__"
        read_only_fields = ("lastmodified",)
        list_serializer_class = BulkListSerializer
        update_lookup_field = "id"
        partial = True


class MlccFurnaceTransitionFilter(filters.FilterSet):
    class Meta:
        model = MlccFurnaceTransition
        fields = {
            "run": ["exact", "in"],
            "resource": ["exact", "in"],
            "predecessor_load": ["exact", "in"],
            "successor_load": ["exact", "in"],
            "transition_rule": ["exact", "in"],
            "transition_type": ["exact", "in"],
            "status": ["exact", "in"],
        }


class MlccFurnaceTransitionSerializer(MlccModelSerializer):
    class Meta:
        model = MlccFurnaceTransition
        fields = "__all__"
        read_only_fields = ("lastmodified",)
        list_serializer_class = BulkListSerializer
        update_lookup_field = "id"
        partial = True


class MlccQualityHoldFilter(filters.FilterSet):
    class Meta:
        model = MlccQualityHold
        fields = {
            "batch_code": ["exact", "in", "contains"],
            "manufacturing_order": ["exact", "in"],
            "hold_type": ["exact", "in"],
            "status": ["exact", "in"],
        }


class MlccQualityHoldSerializer(MlccModelSerializer):
    class Meta:
        model = MlccQualityHold
        fields = "__all__"
        read_only_fields = ("lastmodified",)
        list_serializer_class = BulkListSerializer
        update_lookup_field = "id"
        partial = True


class MlccScheduleRunFilter(filters.FilterSet):
    class Meta:
        model = MlccScheduleRun
        fields = {
            "name": ["exact", "in", "contains"],
            "status": ["exact", "in"],
            "horizon_start": ["exact", "gt", "gte", "lt", "lte"],
            "horizon_end": ["exact", "gt", "gte", "lt", "lte"],
        }


class MlccScheduleRunSerializer(MlccModelSerializer):
    class Meta:
        model = MlccScheduleRun
        fields = "__all__"
        read_only_fields = ("lastmodified",)
        list_serializer_class = BulkListSerializer
        update_lookup_field = "id"
        partial = True


class MlccScheduleResultFilter(filters.FilterSet):
    class Meta:
        model = MlccScheduleResult
        fields = {
            "run": ["exact", "in"],
            "manufacturing_order": ["exact", "in"],
            "resource": ["exact", "in"],
            "furnace_load": ["exact", "in"],
            "batch_code": ["exact", "in", "contains"],
            "status": ["exact", "in"],
        }


class MlccScheduleResultSerializer(MlccModelSerializer):
    class Meta:
        model = MlccScheduleResult
        fields = "__all__"
        read_only_fields = ("lastmodified",)
        list_serializer_class = BulkListSerializer
        update_lookup_field = "id"
        partial = True


def _api_classes(model, serializer, filter_class):
    list_api = type(
        f"{model.__name__}API",
        (frePPleListCreateAPIView,),
        {
            "__module__": __name__,
            "queryset": model.objects.all(),
            "serializer_class": serializer,
            "filter_class": filter_class,
        },
    )
    detail_api = type(
        f"{model.__name__}DetailAPI",
        (frePPleRetrieveUpdateDestroyAPIView,),
        {
            "__module__": __name__,
            "queryset": model.objects.all(),
            "serializer_class": serializer,
        },
    )
    return list_api, detail_api


MlccRecipeAPI, MlccRecipeDetailAPI = _api_classes(
    MlccRecipe, MlccRecipeSerializer, MlccRecipeFilter
)
MlccFurnaceProgramAPI, MlccFurnaceProgramDetailAPI = _api_classes(
    MlccFurnaceProgram,
    MlccFurnaceProgramSerializer,
    MlccFurnaceProgramFilter,
)
MlccFurnaceStateSnapshotAPI, MlccFurnaceStateSnapshotDetailAPI = _api_classes(
    MlccFurnaceStateSnapshot,
    MlccFurnaceStateSnapshotSerializer,
    MlccFurnaceStateSnapshotFilter,
)
MlccFurnaceTransitionRuleAPI, MlccFurnaceTransitionRuleDetailAPI = _api_classes(
    MlccFurnaceTransitionRule,
    MlccFurnaceTransitionRuleSerializer,
    MlccFurnaceTransitionRuleFilter,
)
MlccLoadUnitConversionAPI, MlccLoadUnitConversionDetailAPI = _api_classes(
    MlccLoadUnitConversion,
    MlccLoadUnitConversionSerializer,
    MlccLoadUnitConversionFilter,
)
MlccEquipmentCapabilityAPI, MlccEquipmentCapabilityDetailAPI = _api_classes(
    MlccEquipmentCapability,
    MlccEquipmentCapabilitySerializer,
    MlccEquipmentCapabilityFilter,
)
MlccCompatibilityRuleAPI, MlccCompatibilityRuleDetailAPI = _api_classes(
    MlccCompatibilityRule,
    MlccCompatibilityRuleSerializer,
    MlccCompatibilityRuleFilter,
)
MlccSetupMatrixAPI, MlccSetupMatrixDetailAPI = _api_classes(
    MlccSetupMatrix, MlccSetupMatrixSerializer, MlccSetupMatrixFilter
)
MlccBatchGenealogyAPI, MlccBatchGenealogyDetailAPI = _api_classes(
    MlccBatchGenealogy, MlccBatchGenealogySerializer, MlccBatchGenealogyFilter
)
MlccFurnaceLoadAPI, MlccFurnaceLoadDetailAPI = _api_classes(
    MlccFurnaceLoad, MlccFurnaceLoadSerializer, MlccFurnaceLoadFilter
)
MlccFurnaceLoadItemAPI, MlccFurnaceLoadItemDetailAPI = _api_classes(
    MlccFurnaceLoadItem, MlccFurnaceLoadItemSerializer, MlccFurnaceLoadItemFilter
)
MlccFurnaceTransitionAPI, MlccFurnaceTransitionDetailAPI = _api_classes(
    MlccFurnaceTransition,
    MlccFurnaceTransitionSerializer,
    MlccFurnaceTransitionFilter,
)
MlccQualityHoldAPI, MlccQualityHoldDetailAPI = _api_classes(
    MlccQualityHold, MlccQualityHoldSerializer, MlccQualityHoldFilter
)
MlccScheduleRunAPI, MlccScheduleRunDetailAPI = _api_classes(
    MlccScheduleRun, MlccScheduleRunSerializer, MlccScheduleRunFilter
)
MlccScheduleResultAPI, MlccScheduleResultDetailAPI = _api_classes(
    MlccScheduleResult, MlccScheduleResultSerializer, MlccScheduleResultFilter
)
