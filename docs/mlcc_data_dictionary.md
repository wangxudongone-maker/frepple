# MLCC 数据字典

## 核心模型轻量属性

| 核心表 | 属性 | 类型 | 含义 |
|---|---|---|---|
| `item` | `mlcc_material_type` | string | 材料/半成品类型 |
| `item` | `mlcc_product_family` | string | 产品族，如 X7R、C0G |
| `item` | `mlcc_chip_size` | string | 尺寸代码，如 0603 |
| `item` | `mlcc_layer_count` | integer | 设计层数 |
| `item` | `mlcc_quality_grade` | string | 质量等级 |
| `resource` | `mlcc_equipment_group` | string | MLCC 设备组 |
| `resource` | `mlcc_is_furnace` | boolean | 是否为炉设备 |
| `resource` | `mlcc_nominal_capacity` | decimal | 标称容量 |
| `resource` | `mlcc_load_unit` | string | 炉容量计量单位 |
| `operation` | `mlcc_process_stage` | string | 叠层/层压/切割/排胶/烧结 |
| `operation` | `mlcc_recipe_required` | boolean | 是否必须指定配方 |
| `operation` | `mlcc_batch_required` | boolean | 是否必须追踪批次 |
| `operationplan` | `mlcc_batch_code` | string | MLCC 批次号 |
| `operationplan` | `mlcc_lot_number` | string | 生产批/工单批号 |
| `operationplan` | `mlcc_recipe_version` | string | 执行配方版本 |
| `operationplan` | `mlcc_schedulable` | boolean | 是否允许进入排程 |
| `operationplan` | `mlcc_load_quantity` | decimal | 显式炉装载量 |
| `operationplan` | `mlcc_load_unit` | string | 装载量来源单位 |

## 独立表

| 模型 | 数据库表 | 主键/业务键 | 说明 |
|---|---|---|---|
| `MlccRecipe` | `mlcc_recipe` | `id`；`name + version` 唯一 | 工序配方、版本、生效期、参数 |
| `MlccLoadUnitConversion` | `mlcc_load_unit_conversion` | 物料+来源单位+目标单位唯一 | 精确整数比例的装载单位换算 |
| `MlccEquipmentCapability` | `mlcc_equipment_capability` | `id`；设备+工序+配方+物料唯一 | 设备能力矩阵与批量范围 |
| `MlccCompatibilityRule` | `mlcc_compatibility_rule` | `id`；规则名唯一 | 产品族同炉允许/禁止规则 |
| `MlccSetupMatrix` | `mlcc_setup_matrix` | `id`；设备+工序+前后配方唯一 | 配方切换时间和成本 |
| `MlccBatchGenealogy` | `mlcc_batch_genealogy` | `id`；父批+子批唯一 | 跨工序批次谱系 |
| `MlccFurnaceLoad` | `mlcc_furnace_load` | `id`；`reference` 唯一 | 炉次头、资源、配方、容量、时窗 |
| `MlccFurnaceLoadItem` | `mlcc_furnace_load_item` | `id`；炉次+制造订单唯一 | 炉次内订单/批次及占用量 |
| `MlccQualityHold` | `mlcc_quality_hold` | `id` | 批次/工单冻结与释放信息 |
| `MlccScheduleRun` | `mlcc_schedule_run` | `id`；`name` 唯一 | 一次排程请求的范围、状态和参数 |
| `MlccScheduleResult` | `mlcc_schedule_result` | `id`；运行+制造订单唯一 | 外部求解器的计划结果交换表 |

所有独立表还包含 `source` 和 `lastmodified` 审计字段。

## 枚举

- `process_stage`：`stacking`、`lamination`、`cutting`、`debinding`、`sintering`。
- 同炉规则：`allow`、`forbid`。
- 炉次状态：`draft`、`ready`、`running`、`complete`、`cancelled`、`proposed`。
- 质量冻结状态：`active`、`released`。
- 排程运行状态：`draft`、`ready`、`running`、`complete`、`failed`。
- 排程结果状态：`proposed`、`scheduled`、`blocked`、`not_schedulable`。

## REST API

每种资源同时提供集合和单记录接口，集合接口支持 GET/POST/PUT/DELETE 批量语义，单记录接口支持 GET/PUT/PATCH/DELETE。

| 资源 | 集合地址 | 单记录地址 |
|---|---|---|
| 配方 | `/api/mlcc/mlccrecipe/` | `/api/mlcc/mlccrecipe/{id}/` |
| 装载单位换算 | `/api/mlcc/mlccloadunitconversion/` | `/api/mlcc/mlccloadunitconversion/{id}/` |
| 设备能力 | `/api/mlcc/mlccequipmentcapability/` | `/api/mlcc/mlccequipmentcapability/{id}/` |
| 同炉规则 | `/api/mlcc/mlcccompatibilityrule/` | `/api/mlcc/mlcccompatibilityrule/{id}/` |
| 换型矩阵 | `/api/mlcc/mlccsetupmatrix/` | `/api/mlcc/mlccsetupmatrix/{id}/` |
| 批次谱系 | `/api/mlcc/mlccbatchgenealogy/` | `/api/mlcc/mlccbatchgenealogy/{id}/` |
| 炉次 | `/api/mlcc/mlccfurnaceload/` | `/api/mlcc/mlccfurnaceload/{id}/` |
| 炉次明细 | `/api/mlcc/mlccfurnaceloaditem/` | `/api/mlcc/mlccfurnaceloaditem/{id}/` |
| 质量冻结 | `/api/mlcc/mlccqualityhold/` | `/api/mlcc/mlccqualityhold/{id}/` |
| 排程运行 | `/api/mlcc/mlccschedulerun/` | `/api/mlcc/mlccschedulerun/{id}/` |
| 排程结果 | `/api/mlcc/mlccscheduleresult/` | `/api/mlcc/mlccscheduleresult/{id}/` |

接口沿用 frePPLe 的场景数据库选择、Django 模型权限、批量序列化和过滤机制。

## 关键校验

- 炉次容量和炉次明细数量必须大于 0，且明细合计不能超容量。
- 配方版本和生效日期必填，失效日不能早于生效日。
- 设备能力矩阵不可重复；最大批量不能小于最小批量。
- 同一无序产品族对只能有一条启用规则，禁止产品族与自身形成 `forbid`。
- 新增父子批关系前遍历后代，拒绝任何环。
- 激活的质量冻结会阻止制造订单标记为可排、加入炉次或生成 `proposed/scheduled` 结果。
