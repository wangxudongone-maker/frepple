# MLCC 第二阶段验收说明

## 范围

本阶段交付求解器中立的实例构建、预检、稳定 JSON、REST API、数据检查页面、演示数据和测试。不包含 OR-Tools、优化目标、约束求解或正式排产结果写回。

## 第一阶段复核

- `freppledb.mlcc` 通过 `INSTALLED_APPS` 注册为独立扩展应用。
- MLCC 业务模型位于 `freppledb/mlcc/models.py`，未修改 `freppledb/input/models/` 中的核心模型源码。
- Item、Resource、Operation 和 OperationPlan 的轻量字段通过 `registerAttribute` 和 `AttributeMigration` 扩展。
- 第一阶段 10 张 MLCC 表、管理后台、列表、菜单、REST API、中文翻译、演示数据和校验测试保留。

## 第二阶段入口

装载演示数据：

```bash
python frepplectl.py load_mlcc_solver_demo --dataset valid_demo --batches 100
python frepplectl.py load_mlcc_solver_demo --dataset invalid_demo
```

生成实例并持久化预检记录：

```bash
python frepplectl.py mlcc_build_instance \
  --horizon-days 14 \
  --freeze-hours 48 \
  --source mlcc_valid_demo \
  --output planning_instance.json
```

在标准 Django 部署包装脚本下，也可以使用题目中的 `python manage.py ...` 形式；本源代码仓库的官方入口是 `frepplectl.py`。

REST API：

| 方法和路径 | 用途 |
| --- | --- |
| `POST /api/mlcc/planning-instance/` | 生成实例并返回预检摘要，不持久化 |
| `POST /api/mlcc/precheck/` | 执行预检并持久化运行及问题 |
| `GET /api/mlcc/precheck/<run_id>/` | 查询预检结果，可按 `severity`、`code`、`object_type`、`object_id` 筛选 |

POST 参数包括 `start`、`horizon_days`、`freeze_hours`、`factory_timezone` 和 `source`。接口沿用 frePPLe 的模型权限及场景数据库选择机制。

页面入口：

- `/data/mlcc/precheckrun/`：预检运行、对象数量、BLOCKER/WARNING/INFO 和耗时；
- `/data/mlcc/precheck/`：问题明细，可按错误类型和对象筛选，并通过“定位基础数据”列跳转。

## 验收命令

```bash
python frepplectl.py check
python frepplectl.py makemigrations --check --dry-run mlcc
python frepplectl.py migrate --plan
python frepplectl.py test freppledb.mlcc.tests --verbosity=2
python -m compileall -q freppledb/mlcc
```

生产迁移必须在项目规定的 PostgreSQL 环境执行；SQLite 仅用于当前开发机的兼容性烟雾测试，不能替代 PostgreSQL 验收。

## 验收矩阵

| 标准 | 自动化覆盖 |
| --- | --- |
| valid_demo 无 BLOCKER | `ValidSolverDemoIntegrationTest` |
| invalid_demo 识别 MLCC-P001～MLCC-P016 | `InvalidSolverDemoIntegrationTest` |
| BLOCKER 阻止输出 | `test_blocker_prevents_command_output` |
| 重复业务 JSON 一致 | `test_repeated_extraction_has_identical_business_json` |
| 500 批少于 30 秒 | `test_500_batch_performance_acceptance` |
| 每类规则、时间、Decimal | `test_solver_validator.py` |
| API 权限和响应 | `test_solver_api.py` |
| 表和扩展列 | `test_migrations.py` |

## 已知边界与下一阶段

- 当前物料提取使用可用库存和前序任务预计结束时间；供应订单、替代料及批次级库存策略留待后续扩展。
- 日历区间按当前周期展开，复杂优先级重叠仍由 frePPLe 核心日历语义负责维护。
- 一张客户订单拆分多个 MLCC 批次、批次收率和跨工厂运输尚未建模。
- 下一阶段可在纯 `PlanningInstance` 之上增加求解器适配器、求解参数、软约束评分和结果回写；不得让求解器直接访问 ORM。
