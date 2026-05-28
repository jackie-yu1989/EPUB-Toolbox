# EPUB 工具箱 v1.17.2

[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://www.python.org/)
[![PyQt6](https://img.shields.io/badge/PyQt6-6.4+-green.svg)](https://riverbankcomputing.com/software/pyqt/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Version](https://img.shields.io/badge/Version-1.17.2-orange.svg)](#)

> 集成 Markdown修复、MD转EPUB、EPUB转PDF、EPUB转Word 和组合工作流五大功能的综合性电子书处理工具。

## 📝 版本历史

### v1.17.2 (2026.05.29) — 依赖工具管理增强 + 快捷键扩展

- 🛠️ **依赖工具管理增强**：
  - 支持离线安装（将 `.msi` 放入 `resources/dependencies/` 目录）
  - 支持后台运行模式（系统托盘显示进度，完成后通知）
- ⌨️ **快捷键扩展**：
  - `Ctrl+Q` 清空日志扩展至依赖工具管理
  - `F5` 刷新依赖工具状态
  - `Ctrl+W`/`Esc` 支持关闭依赖工具对话框
- 🧹 **代码优化**：清理未使用的导入，统一快捷键处理逻辑

### v1.17.1 (2026.05.25)

- 📝 快捷键一览表更新：Ctrl+Q 同时清空主窗口和监视面板日志

### v1.17.0 (2026.05.24) — EPUB转Word 排版预设 + 工作流集成

- 📄 **EPUB转Word 新增5种排版预设**：学术论文、书籍排版、商务报告、技术文档、保留原样
- 🎨 **排版预设功能**：支持正文/标题中英文字体分离、字号、行距、首行缩进独立配置
- 🔧 **技术文档预设**：使用 Consolas 等宽字体，适合代码/API 文档
- 🔄 **工作流集成 Word 排版预设**：Word 设置组新增排版预设下拉框
- 🎯 **UI 优化**：工作流模块布局调整，目标文件设置改用靶心图标

### v1.16.0 (2026.05.23) — 工作流 Word 集成 + 常量重构 + 配置持久化

- 🔄 **组合工作流新增 Word 分支**：新增「产出Word」两种模式（直转/全流程），5种工作流模式完整覆盖 PDF/Word/EPUB
- 📄 **EPUB转Word 集成到工作流**：`run_epub2docx_step` 步骤函数就绪，监视面板支持 Word 产物预览与状态追踪
- 🔧 **配置键常量化重构**：新增 `WorkflowKey`、`EPUB2DocxKey`、`EPUB2PdfKey`、`MD2EpubKey` 常量类，全模块零魔法字符串
- 💾 **全模块离焦自动保存**：所有模块实现 `on_activate`/`on_deactivate` 配置持久化钩子，切换模块无缝恢复
- 📊 **监视面板增强**：`StepType.EPUB2DOCX` 枚举就绪，`STEP_NAME_TO_TYPE` / `MODE_STEPS` 映射完整
- 🎨 **UI 优化**：工作流模式按产出格式分组展示，Word 设置区参照 PDF/EPUB 风格统一
- 🐛 **修复**：监视面板 `_start_workflow` 中 Word 参数硬编码问题，改为动态读取 UI 控件值

### v1.15.0 (2026.05.22) — 新增 EPUB转Word 与全局体验跃升

- 🚀 新增「📄 EPUB转Word」模块：支持 EPUB 到 DOCX 的批量转换
- ✨ 独创软回车修复引擎：基于 `python-docx` 与 `lxml`，自动将 Word 软回车(`^l`)拆分/合并为标准硬段落(`^p`)
- 🐛 全局修复"打开输出目录"Bug：通过 `.resolve()` 强制绝对路径化
- 🎨 UI 与视觉优化：EPUB转PDF 图标焕新为 📕，EPUB转Word 页面尺寸改为扁平化单选
- 🧠 配置记忆增强：新增模块离焦自动保存机制

### v1.14.3 (2026.05.17) — PDF 页码、编码修复与体验优化

- 📄 PDF 显示页码：EPUB转PDF 模块新增「显示页码」复选框
- 🐛 修复 Pandoc 中文路径编码问题

### v1.14.0 ~ v1.14.2 (2026.05.09 ~ 2026.05.10) — 监视面板架构重构

- 📊 监视面板架构重构，统一流水线状态管理，修复预览配置闭环

### v1.13.0 (2026.05.03) — 可视化监视面板

- 📊 可视化监视面板上线，CSS 外部配置化系统、MathJax 三级优先级离线渲染

*(更早版本略)*

## 📄 许可证与致谢

**MIT License** | Copyright © 2026 YQJ

### 🙏 致谢

- [Pandoc](https://pandoc.org/) — 通用文档转换器
- [Calibre](https://calibre-ebook.com/) — 电子书管理工具
- [PyQt6](https://riverbankcomputing.com/software/pyqt/) — Python GUI 框架
- [python-docx](https://python-docx.readthedocs.io/) — Word XML 处理库
- [MathJax](https://www.mathjax.org/) — 数学公式渲染引擎
- [keyboard](https://github.com/boppreh/keyboard) — Python 全局键盘监听库
- [Inno Setup](https://jrsoftware.org/isinfo.php) — 安装包制作工具
