# MLCC 求解器输出结构

输出版本仍为 `mlcc-schedule-solution/v1`，第三阶段 B 以向后兼容字段扩展。

## 顶层字段

| 字段 | 说明 |
| --- | --- |
| `status` | `OPTIMAL`、`FEASIBLE` 或明确终止状态 |
| `input_fingerprint` | 稳定排产实例 SHA-256 |
| `solver_name` / `solver_version` | 求解器和固定版本 |
| `parameters` | 时限、线程、随机种子和 `multi_batch_loads` 模式 |
| `assignments` | 全部任务的设备、开始、结束和炉次关联 |
| `furnace_loads` | 明确炉次决策及成员 |
| `orders` | 订单完工、延期、优先级权重 |
| `objective_stages` | 可行、延期、炉次数、总完工时间四个阶段 |
| `phase3a_baseline_metrics` | 单批炉次安全基线 |
| `phase3b_metrics` | 组炉方案指标 |
| `metric_deltas` | B 减 A 的延期、炉次数、完工时间及平均/P50/P90 装载率 ppm |

## `furnace_loads`

每项包含：

- `load_id`、`operation_type`、`equipment_id`；
- `recipe_id`、`recipe_version`、`furnace_program_key`；
- `start_minute`、`end_minute`；
- 整数 `capacity`、`loaded_quantity`、`load_unit`；
- 稳定十进制字符串 `utilization`；
- `member_batch_ids`、`member_task_ids`；
- 每个成员的 `compatibility_evidence` 和 `conversion_evidence`；
- `frozen`、`status`、`constraint_summary`。

每个排胶和烧结任务的 `furnace_load_id` 必须引用且只引用一个炉次。普通任务
该字段为 `null`。

装载率对比以 ppm 整数记录 `average_ppm`、`p50_ppm` 和 `p90_ppm`，避免
不受控浮点数。容量、装载量、时间和所有 CP-SAT 系数均为整数。

## 确定性

数组按稳定 ID 排序，字典键排序，Decimal 写成十进制字符串。求解耗时和
求解界属于运行元数据；输入指纹、业务分配、炉次成员、参数和指标可追溯。
