# MLCC 排产前校验规则

## 结果契约

`PlanningInstanceValidator` 只读取纯 Python `PlanningInstance`。每条问题固定返回：

- `code`：稳定错误码；
- `severity`：`BLOCKER`、`WARNING` 或 `INFO`；
- `object_type` 和 `object_id`；
- 中文 `reason`；
- 中文 `suggestion`；
- `source_field`。

`BLOCKER > 0` 时 `can_start_solver=false`，管理命令不会写出求解器输入，除非显式使用仅供诊断的 `--allow-blockers`。WARNING 允许继续，INFO 仅记录。

## 错误码

| 错误码 | 级别 | 条件 | 主要来源字段 |
| --- | --- | --- | --- |
| `MLCC-P001` | BLOCKER | 批次缺少五道工艺路线或工序 | `operation.mlcc_process_stage` |
| `MLCC-P002` | BLOCKER | 标准加工分钟小于等于 0 | `operation.duration/duration_per` |
| `MLCC-P003` | BLOCKER | 工序没有候选设备 | `operationresource.resource` |
| `MLCC-P004` | BLOCKER | 无启用且匹配工序、产品、配方和数量范围的能力 | `mlcc_equipment_capability` |
| `MLCC-P005` | BLOCKER | 排胶或烧结工序没有配方 | `mlcc_recipe` |
| `MLCC-P006` | BLOCKER | 配方未生效、已失效或被停用 | 配方生效期和 `active` |
| `MLCC-P007` | BLOCKER | 排胶或烧结候选炉容量小于等于 0 | `resource.mlcc_nominal_capacity` |
| `MLCC-P008` | BLOCKER | 数量/批量范围错误或炉装载单位为空 | 工序批量、任务数量、设备装载单位 |
| `MLCC-P009` | BLOCKER | 同一无序产品族对同时存在允许与禁止规则 | `mlcc_compatibility_rule.rule_type` |
| `MLCC-P010` | BLOCKER | 工序依赖图形成循环 | `operation_dependency` |
| `MLCC-P011` | BLOCKER | 活跃质量冻结批仍标记为可排产 | 质量冻结和 `mlcc_schedulable` |
| `MLCC-P012` | BLOCKER | 冻结/已开工任务与设备停机或保养重叠 | 原计划时间、设备日历 |
| `MLCC-P013` | BLOCKER | 所需原料或在制品缺少可用时间 | 库存和在制品预计结束时间 |
| `MLCC-P014` | BLOCKER | 订单、批次或工序数量不守恒 | `Demand.quantity`、`OperationPlan.quantity` |
| `MLCC-P015` | BLOCKER | 最大等待时间小于依赖关系要求的必要间隔 | `operation.mlcc_max_wait_time`、`operation_dependency.hard_safety_leadtime` |
| `MLCC-P016` | WARNING | 交期或原计划时间超出排产周期 | 订单交期、任务原计划时间 |
| `MLCC-P017` | BLOCKER | 单批装载量超过全部候选炉有效容量 | `mlcc_load_quantity`、设备有效容量 |
| `MLCC-P018` | BLOCKER | 炉工序配方不唯一或缺少明确炉程键 | 配方版本、`furnace_program_key` |
| `MLCC-P019` | BLOCKER | 冻结炉次成员、容量、设备、时间或配方不一致 | 炉次及炉次成员表 |
| `MLCC-P020` | BLOCKER | 装载单位缺失、无法换算或不能精确转为整数 | 装载单位及显式换算表 |

## 确定性与去重

问题按严重级别、错误码、对象类型、对象 ID 和来源字段稳定排序。同一对象同一规则产生的重复问题被去重。因此重复预检同一业务快照时，问题集合及顺序一致。

## 演示数据

- `valid_demo`：默认 100 批，可配置为 100～500 批，预检无 BLOCKER。
- `invalid_demo`：故意包含 `MLCC-P001`～`MLCC-P020` 的触发数据；不用于生产基础数据。

```bash
python frepplectl.py load_mlcc_solver_demo --dataset valid_demo --batches 100
python frepplectl.py load_mlcc_solver_demo --dataset invalid_demo
```
