# MLCC 求解器输出结构

当前版本为 `mlcc-schedule-solution/v2`。第三阶段 C 输出仍是仅供预览的计划版本，不修改 `OperationPlan`，不确认计划，也不下发 MES。

## 顶层字段

| 字段 | 说明 |
| --- | --- |
| `status` | `OPTIMAL`、`FEASIBLE`、`INFEASIBLE`、`UNKNOWN` 或 `MODEL_INVALID` |
| `input_fingerprint` | PlanningInstance 业务 JSON 的 SHA-256 |
| `solver_name` / `solver_version` | Google OR-Tools CP-SAT 与固定版本 `9.10.4067` |
| `parameters` | 时限、线程、随机种子和实际 `furnace_mode` |
| `assignments` | 全部任务的设备、起止分钟和炉次关联 |
| `furnace_loads` | 明确炉次、成员、炉程及相邻炉次 |
| `furnace_transitions` | 初始状态或前一炉次到下一炉次的显式转换 |
| `orders` | 订单完工、延期、优先级权重 |
| `objective_stages` | 可行、延期、炉次数、转换分钟、总完工时间五层目标 |
| `solution_mode` | `phase3b_multi_batch`、`phase3a_fallback` 或 `phase3c_transition` |
| `fallback_reason` | 仅安全回退/中间可行快照返回时填写 |
| `last_successful_stage` | 最后成功的分层目标 |
| `phase3b_reference_metrics` | B 原始参考指标、回退来源、C 级有效性、实际用于 C 建模的分组来源及 B/预分炉耗时 |
| `phase3c_metrics` | C 级真实转换约束下的指标及模型构建、validator 等分项耗时 |
| `transition_constraint_cost` | 总转换分钟和来源规则成本；成本仅报告，不进入综合目标 |
| `metric_deltas` | C 相对 B 参考的延期、炉次数、完工时间和新增转换分钟 |

## `furnace_loads`

每项至少包含：

- `load_id`、`operation_type`、`equipment_id`；
- `furnace_program_id`、`furnace_program_key`、`furnace_program_version`；
- `member_recipe_ids`、`member_batch_ids`、`member_task_ids`；
- `recipe_id`、`recipe_version`：仅全部成员使用同一 recipe 时保留，否则均为 `null`；
- `predecessor_load_id`、`successor_load_id`、`setup_before_minutes`；
- `start_minute`、`end_minute`、整数容量/装载量、单位、十进制装载率；
- 兼容证据、单位换算证据、冻结状态和约束摘要。

多个 recipe 映射同一炉程时，严禁以字典序最小 recipe 伪造代表配方。

## `furnace_transitions`

每项包含：

- `transition_id`、`equipment_id`；
- `predecessor_load_id` 或 `initial_state_id`；
- `successor_load_id`；
- `from_state_key`、`to_program_key`；
- `rule_id`、`rule_scope_level`；
- `transition_type`；
- `start_minute`、`end_minute`、`duration_minutes`；
- `frozen`、`status=proposed`；
- `resolution_evidence`，记录作用域、优先级、规则 ID 和缺失规则默认禁止语义。

每台有炉次的设备恰有一条从初始状态进入首炉的转换。其他转换只表示相邻炉次，不为同一炉次中的成员创建内部转换。

## 状态和安全语义

- B 方案只作为分组、提示和指标参照；没有转换记录的 B 方案不能作为 C 级回退。
- `MODEL_INVALID` 不含业务分配且禁止持久化。
- `INFEASIBLE`、`UNKNOWN` 在没有 C 级可行快照时不返回 B 分配。
- 超时只有在独立 C 级 validator 已验证过中间快照时才返回 `FEASIBLE`，并填写 `fallback_reason`。
- validator 失败禁止持久化；持久化始终在单个数据库事务中，状态仅为 `proposed`。

## 确定性

数组按稳定业务 ID 排序，字典键排序，`Decimal` 写为十进制字符串。运行耗时和最优界是运行元数据；输入指纹、版本、求解参数、任务、炉次、转换和规则证据可完整追溯。
