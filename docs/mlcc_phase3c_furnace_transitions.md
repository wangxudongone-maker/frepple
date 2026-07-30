# MLCC 第三阶段 C：序列相关炉程转换

## 范围

第三阶段 C 在第三阶段 B 的明确炉次和成员关系之上增加排胶、烧结炉的相邻顺序及炉状态转换。叠层、层压、切割仍是普通有限产能任务。本阶段：

- 不修改或覆盖 `OperationPlan`；
- 不确认生产计划，不下发 MES；
- 不实现计划稳定性、拖拽甘特图或人工确认流程；
- 固定使用 OR-Tools `9.10.4067`。

## 数据流和求解边界

```text
PostgreSQL
  └─ PlanningInstanceExtractor
       └─ PlanningInstance v2
            ├─ PlanningInstanceValidator (P001-P025)
            ├─ Phase 3B grouping reference
            └─ Phase 3C CP-SAT adjacency model
                 └─ SchedulingSolution v2
                      ├─ independent solution validator
                      └─ atomic proposed-preview persistence
```

求解器只读取冻结 dataclass 或其 JSON，不导入 Django 模型。ORM 只存在于提取器和预览持久化适配器。

## 炉程、状态和转换规则

`MlccFurnaceProgram` 是一等可执行对象。它明确描述版本、工序、气氛、所需前状态和执行后状态。`MlccRecipe.furnace_program` 是显式外键；多个配方可以映射同一炉程。

`MlccFurnaceStateSnapshot` 记录设备在某时刻的状态及可用时间。提取器只选择排产起点前最新记录。

`MlccFurnaceTransitionRule` 的解析顺序是：

1. 精确设备；
2. 设备组；
3. 全局；
4. 在选定层级选择最小优先级数值。

同层级同优先级多条有效规则是冲突。缺少规则默认禁止。相同炉程连续运行也必须维护显式自转换规则。

## CP-SAT 相邻弧模型

第三阶段 C 保留第三阶段 B 已确定的炉次成员分组，再优化炉次设备、时间和相邻顺序，不退回批次级全量两两排序。

每台候选炉建立一个 `AddCircuit`：

- 虚拟节点 `0` 表示排产起点炉状态；
- 每个炉次在该设备上有一个分配变量；
- 未分配到该设备的炉次选择 self-loop；
- 设备未使用时虚拟节点选择 self-loop；
- 设备有炉次时恰好一条 `0 → 首炉` 弧和一条 `末炉 → 0` 弧；
- 只为同一候选设备上、具有显式允许规则且时间上可能相邻的炉次创建 `i → j` 弧。

选中相邻弧时：

```text
transition.start >= predecessor.end
transition.end <= successor.start
transition.duration == resolved_rule.duration
```

非冻结转换紧贴后继炉次结束；冻结转换保持原开始和结束。转换创建可选区间，和炉次、普通任务一起进入设备 `NoOverlap`。区间还必须完整落在班次可用段内，因此不能跨越停机、保养或不可用日历。

冻结炉次固定设备、时间、成员和炉程；冻结转换固定前驱、后继、设备、规则和时间。

## 分层目标

目标逐层求解并锁定上一层结果：

1. 严格可行；
2. 最小化加权延期；
3. 最小化炉次数；
4. 最小化总转换分钟；
5. 最小化总完工时间。

`setup_cost` 只汇总到报告，不与时间、能耗或货币混合成未经验证的总分。

## 第三阶段 B 参考和回退

第三阶段 B 只提供炉次分组、求解提示和指标参照。输出记录：

- `phase3b_reference_metrics`；
- `valid_under_phase3c_constraints`；
- `phase3c_metrics`；
- `transition_constraint_cost`；
- C 相对 B 的指标差。

当第三阶段 B 因时限返回经过验证的第三阶段 A 单批炉次时，C 阶段不会在全部单批炉次上建立全量相邻弧。它按工序、显式炉程、候选设备、兼容范围及上游炉次释放边界进行确定性预分炉，单个预分炉最多 32 个成员；冻结炉次及其上游炉工序祖先保持原分组。预分炉只是缩小 C 模型的种子，不会被标记为 B 的求解结果，最终排程仍必须通过独立 C 级 validator。

`phase3b_reference_metrics` 明确记录 `raw_solution_mode`、`raw_fallback_reason`、`raw_furnace_load_count`、`grouping_source`、`grouping_furnace_load_count`、B 参考耗时和预分炉耗时，保证回退来源和性能证据可审计。

B 没有转换时间，因此 B/C 延期差不是算法退化结论。未经 C 级 validator 验证的 B 解绝不作为 C 的回退：

- 构建错误或 CP-SAT 模型错误返回 `MODEL_INVALID`；
- 没有 C 级可行解返回 `INFEASIBLE` 或 `UNKNOWN`；
- 只有已经通过独立 C 级 validator 的中间快照可以在后续目标超时时以 `FEASIBLE` 返回。

## 独立校验器

`SchedulingSolutionValidator` 不调用 CP-SAT，复验第三阶段 B 的全部硬约束，并额外验证：

- 每台炉形成一条覆盖全部炉次的无环路径；
- 每个炉次恰有一条入转换，至多一个业务后继；
- 首炉引用正确初始状态；
- 规则方向、作用域、优先级、生效期和时长解析唯一；
- 炉程执行后状态与下一条转换来源状态连续；
- 炉次、转换、普通任务和不可用日历不重叠；
- 冻结炉次及冻结转换未变化；
- 混合 recipe 炉次不伪造代表 recipe。

任何违反都会阻止持久化。

## 命令和 API

加载演示数据：

```bash
python frepplectl.py load_mlcc_solver_demo \
  --dataset transition_demo --batches 100
```

生成 C 级预览：

```bash
python frepplectl.py mlcc_solve \
  --solver-phase phase3c \
  --source mlcc_transition_demo \
  --start 2026-01-05T00:00:00 \
  --horizon-days 180 \
  --freeze-hours 48 \
  --max-time-seconds 120 \
  --output examples/mlcc_furnace_transition_solution.json
```

REST：

```http
POST /api/mlcc/solve/
Content-Type: application/json

{
  "solver_phase": "phase3c",
  "source": "mlcc_transition_demo",
  "start": "2026-01-05T00:00:00",
  "horizon_days": 180,
  "freeze_hours": 48,
  "max_time_seconds": 120,
  "persist": true
}
```

`solver_phase=phase3b` 仍可用于安全对比。默认是 `phase3c`。

## 预览持久化

成功结果在一个数据库事务中写入：

- `MlccScheduleRun`；
- `MlccFurnaceLoad` / `MlccFurnaceLoadItem`；
- `MlccFurnaceTransition`；
- `MlccScheduleResult`。

状态均保持 `proposed` 语义。业务哈希包含任务和转换，同一解重复保存返回同一 ScheduleRun。任意转换、成员或结果写入失败时整个事务回滚。
