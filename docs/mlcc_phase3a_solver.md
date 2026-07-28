# MLCC 第三阶段 A：CP-SAT 有限产能基线

## 范围

本阶段实现与 Django ORM 解耦的通用有限产能基线。求解器只接收
`PlanningInstance` 或 `mlcc-planning-instance/v1` JSON，不查询数据库。
排胶炉和烧结炉采用“一批一炉次”，不实现同炉混批、炉次拼装或正式计划下发。

## 模块

| 文件 | 职责 |
| --- | --- |
| `solver/phase3a.py` | 第三阶段 A CP-SAT 建模、三阶段分层求解和状态处理 |
| `solver/constraints.py` | 设备资格、班次和停机区间等共享纯函数 |
| `solver/solution.py` | `mlcc-schedule-solution/v1` 输出结构和稳定 JSON |
| `solver/solution_validator.py` | 不调用求解器的独立硬约束校验 |
| `solver/solve_service.py` | 将已校验解写入独立 MLCC 预览表 |

`phase3a.py`、`constraints.py`、`solution.py` 和 `solution_validator.py`
不导入 Django，也不接收 ORM 对象。

## 硬约束

- 每个可排产任务只选择一台候选且通过能力认证的设备；
- 同一设备上的任务不重叠；
- 叠层、层压、切割、排胶和烧结遵守前后依赖及最小/最大等待；
- 任务必须完整落在设备班次内，且不与停机或保养重叠；
- 原料和在制品可用前不得开工；
- 已开工和冻结任务固定设备、开始与结束分钟；
- 所有任务位于排产周期内；
- 能力数量范围、炉容量和装载单位必须适配；
- 排胶与烧结按一批一炉次建模。

质量冻结且已标记为可排产会产生预检 BLOCKER。不可排产批次中的未开工任务
不进入模型；已开工或冻结任务仍作为固定任务保留。

## 分层优化

求解按严格顺序执行：

1. 不设置目标，先寻找满足全部硬约束的可行解；
2. 最小化加权延期，并锁定本阶段得到的延期值；
3. 在不恶化延期值的前提下最小化总完工时间。

frePPLe 中较小的优先级数字代表更高优先级。权重按当前输入中的优先级范围
反向归一化，优先级 1 获得最大权重。求解参数、OR-Tools 版本、每阶段状态、
目标值、最佳界、耗时和最终最优间隙均写入结果。

## 命令

从数据库提取并求解：

```bash
python frepplectl.py mlcc_solve \
  --horizon-days 45 \
  --freeze-hours 48 \
  --source mlcc_solver_valid_demo \
  --max-time-seconds 60 \
  --workers 1 \
  --output mlcc_schedule_solution.json
```

从稳定 JSON 求解：

```bash
python frepplectl.py mlcc_solve \
  --input planning_instance.json \
  --max-time-seconds 60 \
  --output mlcc_schedule_solution.json
```

增加 `--persist-preview` 会新建 `MlccScheduleRun` 和状态为 `proposed` 的
`MlccScheduleResult`。该操作不更新 `OperationPlan`，不覆盖已确认计划，
也不下发生产。

## REST API

`POST /api/mlcc/solve/`

请求沿用排产实例接口的 `start`、`horizon_days`、`freeze_hours`、`source`
和 `factory_timezone` 参数，并支持：

- `max_time_seconds`：总求解时限；
- `workers`：搜索线程数，默认 1 以保持确定性；
- `random_seed`：随机种子，默认 0；
- `persist`：是否保存独立预览版本，默认 `true`。

有 BLOCKER 时返回 HTTP 409 和 `BLOCKED`，不会创建 CP-SAT 模型。
`INFEASIBLE`、`UNKNOWN` 和 `MODEL_INVALID` 返回 HTTP 422 及明确状态。

## 输出

输出至少包含输入指纹、求解器名称与版本、全部参数、阶段状态、每个任务的
设备和相对分钟、订单完工与延期、目标值、耗时和最优间隙。示例见
`examples/mlcc_schedule_solution.json`。

## 当前边界

- 未实现同炉混批、装炉组合和兼容族组批；
- 未把换型矩阵作为序列相关准备时间加入 CP-SAT；
- 未做跨工厂、替代工艺路线、拆批或合批；
- 只生成预览，不执行生产计划确认或下发。

第三阶段 B 已将本实现保留为安全上界和超时回退，详见
`docs/mlcc_phase3b_furnace_batching.md`。
