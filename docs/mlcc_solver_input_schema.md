# MLCC 排产输入数据结构

## 目的与边界

`freppledb.mlcc.solver` 将 frePPLe 基础数据和 MLCC 扩展表转换为求解器中立的 `PlanningInstance`。数据库访问仅存在于 `extractor.py`；schema、预检、CP-SAT 和 solution validator 都不接收 Django ORM 对象。

数据流如下：

```text
frePPLe/MLCC 数据库 → PlanningInstanceExtractor → PlanningInstance
                                              ├→ PlanningInstanceValidator → PrecheckReport
                                              └→ 稳定 JSON / SHA-256 指纹
```

## 通用约定

- `schema_version` 当前为 `mlcc-planning-instance/v2`；反序列化仍接受 v1，缺失的第三阶段 C 集合按空集合处理。
- 所有业务对象 ID 使用带类型前缀的稳定字符串，例如 `batch:MLCC-P2-V-0001`、`task:MLCC-P2-V-MO-0001-1`。
- 数量、批量和容量在内存中使用 `Decimal`，JSON 中编码为十进制字符串；禁止转换为二进制浮点数。
- `window.origin` 是带 UTC 偏移的 ISO 8601 时间。其他业务时间统一为相对该起点的整数分钟。
- 数据库时间继续遵循 frePPLe 的工厂本地时间配置；提取时附加 `factory_timezone`，不改变核心表的时间字段。
- 元组和列表由提取器按稳定 ID 排序，字典键按名称排序。相同数据库快照和参数产生相同业务 JSON 与指纹。
- 炉状态、转换规则和冻结转换的 ID 由业务字段计算 SHA-256，不包含数据库自增主键。
- `PlanningInstance` 是冻结的 Python dataclass 集合，后续求解器不能通过它访问 ORM。

## 顶层结构

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `window` | `PlanningWindow` | 排产起点、周期、冻结窗口和工厂时区 |
| `customer_orders` | `CustomerOrder[]` | 客户订单、数量、交期和优先级 |
| `batches` | `ProductionBatch[]` | 生产批次、产品族及质量状态 |
| `steps` | `ProcessStep[]` | 五道工序任务及依赖关系 |
| `equipment` | `Equipment[]` | 候选设备、容量、装载单位和日历 |
| `capabilities` | `EquipmentCapability[]` | 设备—工序—产品—配方认证 |
| `recipes` | `Recipe[]` | 配方版本、生效期、换型族及参数 |
| `furnace_programs` | `FurnaceProgram[]` | 一等、带版本的可执行炉程及前后炉状态 |
| `furnace_state_snapshots` | `FurnaceStateSnapshot[]` | 排产起点前每台候选炉最新状态 |
| `furnace_transition_rules` | `FurnaceTransitionRule[]` | 初始/前序状态到目标炉程的显式转换 |
| `compatibility_rules` | `CompatibilityRule[]` | 同炉允许/禁止规则 |
| `setup_rules` | `SetupRule[]` | 配方切换时间 |
| `materials` | `MaterialAvailability[]` | 原料和在制品数量及可用分钟 |
| `frozen_furnace_loads` | `FrozenFurnaceLoad[]` | 不可移动的既有炉次 |
| `frozen_furnace_transitions` | `FrozenFurnaceTransition[]` | 不可改变的既有炉次顺序与转换 |

## 主要对象

### PlanningWindow

- `origin`：排产起点，ISO 8601 字符串。
- `horizon_minutes`：排产周期总分钟数。
- `freeze_minutes`：冻结窗口分钟数。
- `timezone`：IANA 时区名，例如 `Asia/Shanghai`。

### CustomerOrder 与 ProductionBatch

订单包括稳定 ID、产品、批次、`Decimal` 数量、相对交期和优先级。批次额外包括产品族、质量冻结标志和 `schedulable` 标志。当前演示数据采用一个订单对应一个生产批次，数据结构仍保留独立 ID 以支持后续拆批。

### ProcessStep

每个任务包括：

- `stage`：`stacking`、`lamination`、`cutting`、`debinding`、`sintering` 之一；
- 标准加工分钟、最小/最大批量；
- 候选设备和通过认证的设备 ID；
- 已分配设备、配方及前序任务 ID；
- 依赖关系要求的最小等待分钟、工序允许的最大等待分钟和所需物料 ID；
- `started`、`frozen`；
- 原计划开始/结束相对分钟。

### Equipment 与 CalendarInterval

设备包含容量、装载单位，以及三类区间：`shifts`、`downtimes`、`maintenance`。区间全部采用 `[start_minute, end_minute)` 半开区间。

### EquipmentCapability

能力记录匹配设备、工序、可选产品、可选配方及数量上下限。`enabled=false` 的能力保留在输入中，但不构成有效认证。

### Recipe、FurnaceProgram 与炉状态

`Recipe.furnace_program_id` 显式指向一个 `FurnaceProgram`。多个 recipe 可以映射同一 program；旧 `furnace_program_key` 仅用于迁移兼容，两个字段同时存在时必须一致。

`FurnaceProgram` 包含稳定业务 ID、炉程键、版本、工序、气氛、所需前状态、执行后状态、生效期和启用状态。`FurnaceStateSnapshot` 记录设备观察时间、状态、当前炉程和最早可用分钟；提取器只选择排产起点前最新记录。

`FurnaceTransitionRule` 包含设备/设备组/全局作用域、来源状态、目标炉程、转换类型、整数分钟、成本、允许标志、优先级和生效期。解析顺序严格为精确设备 > 设备组 > 全局，同级同优先级多条规则视为冲突，缺少规则默认禁止。相同炉程连续运行也必须有显式自转换规则。

### CompatibilityRule 与 SetupRule

配方保留版本、生效/失效日期、启用状态、换型族和参数字典。同炉规则将产品族对视为无序组合。换型规则记录可选设备、工序、起止配方及换型分钟。

### MaterialAvailability

`kind` 为 `raw_material` 或 `work_in_progress`。`available_minute=null` 表示无法确定可用时间，会产生 BLOCKER。

## ORM 来源映射

| 输入结构 | 主要来源 |
| --- | --- |
| 订单/批次 | `Demand`、`OperationPlan` 及 MLCC 轻量属性 |
| 工序与依赖 | `Operation`、`OperationDependency`、`OperationPlan` |
| 候选/已分配设备 | `OperationResource`、`OperationPlanResource` |
| 设备和日历 | `Resource`、`Calendar`、`CalendarBucket` |
| 能力/配方/炉程/炉状态/转换 | `MlccEquipmentCapability`、`MlccRecipe`、`MlccFurnaceProgram`、`MlccFurnaceStateSnapshot`、`MlccFurnaceTransitionRule` |
| 同炉/旧换型 | `MlccCompatibilityRule`、`MlccSetupMatrix` |
| 冻结炉次与顺序 | `MlccFurnaceLoad`、`MlccFurnaceLoadItem`、`MlccFurnaceTransition` |
| 原料/在制品 | `OperationMaterial`、`Buffer`、前序任务预计结束时间 |
| 质量冻结 | `MlccQualityHold`、`OperationPlan.mlcc_schedulable` |

完整示例见 `examples/mlcc_planning_instance.json`。
