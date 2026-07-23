# MLCC 行业扩展架构

## 目标与边界

`freppledb.mlcc` 是 frePPLe 9.17.0 的独立扩展应用，用于承载 MLCC 排产所需的行业主数据、炉次、批次谱系、质量冻结以及排程输入输出。本阶段只建设数据与集成框架，不包含 OR-Tools 或其他求解算法。

扩展遵循 frePPLe 官方 extension app 机制：

- `Item`、`Resource`、`Operation`、`OperationPlan`（制造订单的底层表）通过 `registerAttribute` 和 `AttributeMigration` 增加轻量字段；
- 不修改 `freppledb.input.models` 中的核心业务模型代码；
- 独立业务表统一使用 `mlcc_*` 表名；
- 后台、GridReport、菜单和 REST API 均由 `freppledb.mlcc` 自注册；
- `djangosettings.py` 仅增加应用启用项，并保留中文默认语言配置。

## 组件

| 组件 | 文件 | 职责 |
|---|---|---|
| 应用元数据 | `freppledb/mlcc/__init__.py` | 在 frePPLe 应用管理中说明扩展 |
| 轻量属性 | `attributes.py`、迁移 `0002` | 扩展 Item、Resource、Operation、ManufacturingOrder |
| 独立模型 | `models.py`、迁移 `0001` | MLCC 主数据、执行数据和排程交换数据 |
| 管理与列表 | `admin.py`、`views.py`、`menu.py` | 编辑页面、列表、导入导出和菜单 |
| REST API | `serializers.py`、`urls.py` | 批量/单记录 CRUD、过滤和权限控制 |
| 质量闸门 | `models.py`、`signals.py` | 阻止冻结批进入可排产、炉次或已排状态 |
| 演示数据 | `management/commands/load_mlcc_demo.py` | 幂等加载五工序演示数据 |
| 自动测试 | `tests/` | 模型、API、迁移、校验和演示数据测试 |

## 数据流

1. frePPLe 核心主数据描述物料、设备、工序和制造订单。
2. MLCC 配方、设备能力、同炉规则和换型矩阵补充行业约束。
3. 批次谱系和质量冻结记录生产追溯及可排性。
4. 炉次及炉次明细表示排胶/烧结的批处理载荷。
5. 外部求解器未来读取上述数据，写入 `MlccScheduleRun` 和 `MlccScheduleResult`。
6. 本阶段的演示结果明确标记 `solver_generated=false`，不伪装为求解结果。

## 安装与运行

```bash
frepplectl migrate
frepplectl load_mlcc_demo
frepplectl test freppledb.mlcc
```

指定场景数据库时使用 `--database scenario1`。Docker 开发方式沿用仓库 `.devcontainer`（应用容器 + PostgreSQL 16）；生产镜像仍使用仓库的 CMake/Docker 构建链。

## 校验策略

独立模型在每次 `save` 前执行 `full_clean`，API 将 Django 校验错误转换为 HTTP 400。数据库约束负责正容量、正装载量和关键唯一性；跨行/跨表规则由模型校验负责。质量冻结还通过制造订单保存信号覆盖核心 API 和导入路径。
