# MLCC 第三方依赖与许可证

| 依赖 | 固定版本 | 用途 | 许可证 | 官方来源 |
| --- | --- | --- | --- | --- |
| Google OR-Tools | 9.10.4067 | CP-SAT 有限产能排程 | Apache License 2.0 | <https://pypi.org/project/ortools/9.10.4067/> |
| Abseil Python | 由 OR-Tools 元数据解析 | OR-Tools 基础工具 | Apache License 2.0 | <https://pypi.org/project/absl-py/> |
| immutabledict | 由 OR-Tools 元数据解析 | 不可变映射 | MIT License | <https://pypi.org/project/immutabledict/> |
| NumPy | 由 OR-Tools 元数据解析 | 数值数组运行时 | BSD-3-Clause | <https://pypi.org/project/numpy/> |
| pandas | 由 OR-Tools 元数据解析 | OR-Tools Python 数据接口 | BSD-3-Clause | <https://pypi.org/project/pandas/> |
| Protocol Buffers | 由 OR-Tools 元数据解析 | 求解器消息序列化 | BSD-3-Clause | <https://pypi.org/project/protobuf/> |

选择 9.10.4067 是为了同时覆盖 frePPLe 9.17 声明的 Python 3.8 下限和
验收环境 Python 3.12。PyPI 提供 Python 3.8～3.12、Windows 和 Linux 的
预编译 Wheel。

OR-Tools 的传递依赖由其 Wheel 元数据声明并由 pip 解析。生产镜像构建应保存
完整的解析后依赖清单和 Wheel 哈希；不得在运行时自动升级为未验收版本。
现有 `python-dateutil` 从 2.8.1 升级到 2.8.2，以满足 pandas 的
`python-dateutil>=2.8.2` 约束。
