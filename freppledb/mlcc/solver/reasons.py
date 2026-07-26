"""Stable MLCC precheck codes, Chinese reasons and repair guidance."""

from dataclasses import dataclass
from enum import StrEnum


class Severity(StrEnum):
    BLOCKER = "BLOCKER"
    WARNING = "WARNING"
    INFO = "INFO"


@dataclass(frozen=True, slots=True)
class ReasonDefinition:
    code: str
    severity: Severity
    reason: str
    suggestion: str
    source_field: str


@dataclass(frozen=True, slots=True)
class PrecheckIssue:
    code: str
    severity: str
    object_type: str
    object_id: str
    reason: str
    suggestion: str
    source_field: str


REASONS = {
    "MISSING_ROUTING": ReasonDefinition(
        "MLCC-P001",
        Severity.BLOCKER,
        "批次缺少完整的五道工艺路线或工序。",
        "补齐叠层、层压、切割、排胶和烧结工序及其顺序。",
        "operation.mlcc_process_stage",
    ),
    "INVALID_STANDARD_TIME": ReasonDefinition(
        "MLCC-P002",
        Severity.BLOCKER,
        "工序标准加工时间无效。",
        "维护大于零的固定工时或单位工时。",
        "operation.duration/duration_per",
    ),
    "NO_AVAILABLE_RESOURCE": ReasonDefinition(
        "MLCC-P003",
        Severity.BLOCKER,
        "工序没有候选设备。",
        "为工序维护有效的 OperationResource。",
        "operationresource.resource",
    ),
    "MISSING_CAPABILITY": ReasonDefinition(
        "MLCC-P004",
        Severity.BLOCKER,
        "候选设备缺少 MLCC 能力或认证。",
        "维护启用的设备能力矩阵，并匹配工序、物料和配方。",
        "mlcc_equipment_capability",
    ),
    "MISSING_RECIPE": ReasonDefinition(
        "MLCC-P005",
        Severity.BLOCKER,
        "排胶或烧结工序缺少配方。",
        "为工序或物料维护有效版本的 MLCC 配方。",
        "mlcc_recipe",
    ),
    "INVALID_RECIPE": ReasonDefinition(
        "MLCC-P006",
        Severity.BLOCKER,
        "排胶或烧结配方未生效、已失效或被停用。",
        "调整配方生效期或选择当前有效版本。",
        "mlcc_recipe.effective_date/expiry_date/active",
    ),
    "INVALID_FURNACE_CAPACITY": ReasonDefinition(
        "MLCC-P007",
        Severity.BLOCKER,
        "排胶或烧结候选炉的容量无效。",
        "维护大于零的炉设备标称容量。",
        "resource.mlcc_nominal_capacity",
    ),
    "INVALID_BATCH_OR_LOAD_UNIT": ReasonDefinition(
        "MLCC-P008",
        Severity.BLOCKER,
        "批量范围、任务数量或炉装载单位无效。",
        "修正工序最小/最大批量、任务数量及设备装载单位。",
        "operation.sizeminimum/sizemaximum/resource.mlcc_load_unit",
    ),
    "COMPATIBILITY_CONFLICT": ReasonDefinition(
        "MLCC-P009",
        Severity.BLOCKER,
        "同一产品族组合存在互相矛盾的同炉规则。",
        "仅保留一条启用的允许或禁止规则，并统一产品族顺序。",
        "mlcc_compatibility_rule.rule_type",
    ),
    "DEPENDENCY_CYCLE": ReasonDefinition(
        "MLCC-P010",
        Severity.BLOCKER,
        "工序依赖形成循环。",
        "删除反向或重复依赖，保证工艺路线为有向无环图。",
        "operation_dependency",
    ),
    "HELD_BATCH_SCHEDULABLE": ReasonDefinition(
        "MLCC-P011",
        Severity.BLOCKER,
        "质量冻结批仍被标记为可排产。",
        "释放质量冻结，或将批次及相关制造订单设为不可排产。",
        "mlcc_quality_hold/status/mlcc_schedulable",
    ),
    "FROZEN_DOWNTIME_CONFLICT": ReasonDefinition(
        "MLCC-P012",
        Severity.BLOCKER,
        "冻结区任务与设备停机或保养时间冲突。",
        "调整冻结任务、设备分配或停机保养窗口。",
        "operationplan.startdate/enddate/resource.available",
    ),
    "MATERIAL_AVAILABILITY_MISSING": ReasonDefinition(
        "MLCC-P013",
        Severity.BLOCKER,
        "原料或在制品缺少可用时间。",
        "维护库存、供应计划或在制品预计可用时间。",
        "buffer.onhand/operationplanmaterial.flowdate",
    ),
    "QUANTITY_IMBALANCE": ReasonDefinition(
        "MLCC-P014",
        Severity.BLOCKER,
        "订单、批次与工序数量不守恒。",
        "核对订单数量、批次数量及各工序投入产出数量。",
        "demand.quantity/operationplan.quantity",
    ),
    "MAX_WAIT_TOO_SHORT": ReasonDefinition(
        "MLCC-P015",
        Severity.BLOCKER,
        "工序最大等待时间小于必要加工间隔。",
        "增大最大等待时间，或缩短前序加工及转运间隔。",
        "operation.mlcc_max_wait_time/operation_dependency.hard_safety_leadtime",
    ),
    "OUTSIDE_HORIZON": ReasonDefinition(
        "MLCC-P016",
        Severity.WARNING,
        "订单或任务时间超出排产周期。",
        "扩大排产周期，或调整订单交期和原计划时间。",
        "demand.due/operationplan.startdate/enddate",
    ),
}


def issue(reason_key, object_type, object_id, detail=None):
    definition = REASONS[reason_key]
    reason = definition.reason
    if detail:
        reason = f"{reason} {detail}"
    return PrecheckIssue(
        code=definition.code,
        severity=definition.severity.value,
        object_type=object_type,
        object_id=str(object_id),
        reason=reason,
        suggestion=definition.suggestion,
        source_field=definition.source_field,
    )
