# frePPLe 简体中文说明

本 Fork 在 frePPLe 官方源码的基础上完善简体中文界面，并将新安装实例的默认语言设为简体中文。

## 中文化范围

- 补齐简体中文主词典中的全部空翻译。
- 同步 Django、JavaScript、Angular 和 Vue 运行时翻译资源。
- 修正模糊翻译、繁体字混入和常见制造业术语。
- 保留英文、繁体中文及其他上游语言。
- 保留所有模板变量、HTML 标签和 API 命令。

## 默认语言

默认语言为 `zh-hans`。如需切换，可在启动服务前设置环境变量：

```bash
export FREPPLE_LANGUAGE_CODE=en
```

该变量可设置为 `djangosettings.py` 的 `LANGUAGES` 列表中任一语言代码。

## 重新生成翻译资源

修改 `freppledb/locale/zh_Hans/zh_Hans.po` 后，在已经配置好 frePPLe 开发环境的 Linux 终端中运行：

```bash
./translations.sh compile
```

如果使用容器或安装包，请在修改后重新构建，确保生成的语言资源进入最终镜像或软件包。

## 原项目文档

安装、构建、数据库配置和生产部署方式仍以[官方 README](README.md)及[官方文档](https://frepple.com/docs/current/)为准。
