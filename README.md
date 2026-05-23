# EPUB 工具箱 v1.16.0

[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://www.python.org/)
[![PyQt6](https://img.shields.io/badge/PyQt6-6.4+-green.svg)](https://riverbankcomputing.com/software/pyqt/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Version](https://img.shields.io/badge/Version-1.16.0-orange.svg)](#)

> 集成 MD公式修复、MD转EPUB、EPUB转PDF、EPUB转Word 和组合工作流五大功能的综合性电子书处理工具。

## 📋 目录

- [环境依赖](#-环境依赖)
- [快速开始](#-快速开始)
- [功能详解](#-功能详解)
- [使用示例](#-使用示例)
- [实现原理](#-实现原理)
- [快捷键一览](#-快捷键一览)
- [依赖工具管理](#-依赖工具管理)
- [项目优点](#-项目优点)
- [版本历史](#-版本历史)
- [许可证与致谢](#-许可证与致谢)

## 🚀 环境依赖

### 一、Python 包（pip install）

| 包名              | 用途                            | 必需？            |
| :---------------- | :------------------------------ | :---------------- |
| pyqt6             | GUI 框架                        | ✅ 必需            |
| python-docx, lxml | DOCX XML 级后处理（软回车修复） | ✅ EPUB转Word 必需 |
| Pillow            | 图片处理（纵横比校准）          | ⚠️ EPUB转Word 可选 |
| pyqt6-webengine   | 公式渲染预览                    | ⚠️ 可选            |
| keyboard          | 全局热键唤醒                    | ⚠️ 可选            |

### 二、外部工具（系统安装）

| 工具                        | 用途                       | 必需？                |
| :-------------------------- | :------------------------- | :-------------------- |
| pandoc                      | MD 转 EPUB 核心转换引擎    | ✅ MD转EPUB 必需       |
| calibre（含 ebook-convert） | EPUB 转 PDF / EPUB 转 Word | ✅ EPUB转PDF/Word 必需 |

### 三、Mermaid 图表渲染（可选）

| 工具                | 用途                           | 安装方式                                      |
| :------------------ | :----------------------------- | :-------------------------------------------- |
| Node.js             | mmdc 的运行环境                | [nodejs.org](https://nodejs.org/) 下载 LTS 版 |
| mmdc（Mermaid CLI） | MD 转 EPUB 时渲染 Mermaid 图表 | `npm install -g @mermaid-js/mermaid-cli`      |

### 四、测试依赖（可选）

| 依赖       | 用途       | 安装方式                 |
| :--------- | :--------- | :----------------------- |
| pytest     | 测试框架   | `pip install pytest`     |
| pytest-cov | 覆盖率报告 | `pip install pytest-cov` |

### 五、依赖矩阵

| 功能模块                   | Python 包                 | 外部工具                |
| :------------------------- | :------------------------ | :---------------------- |
| 主界面 + 所有模块          | pyqt6                     | —                       |
| MD 公式修复                | —（纯 Python）            | —                       |
| MD 转 EPUB                 | —                         | pandoc                  |
| MD 转 EPUB（Mermaid 图表） | —                         | pandoc + Node.js + mmdc |
| EPUB 转 PDF                | —                         | calibre                 |
| EPUB 转 Word               | python-docx, lxml, Pillow | calibre                 |
| 组合工作流                 | —                         | pandoc + calibre        |
| 监视面板                   | —                         | —                       |
| 公式预览渲染               | pyqt6-webengine           | —                       |
| 全局热键唤醒               | keyboard                  | —                       |

## 🏃 快速开始

```bash
# 1. 安装 Python 包
pip install pyqt6 python-docx lxml Pillow pyqt6-webengine keyboard

# 2. 安装外部工具
winget install Pandoc
winget install Calibre

# 3. 可选：安装 Mermaid 图表渲染
winget install OpenJS.NodeJS
npm install -g @mermaid-js/mermaid-cli

# 4. 运行
python main.py

```

## 🎯 功能详解

### 🔄 组合工作流 — 5种模式 + 📊 可视化监视面板

自动编排 MD修复 → MD转EPUB → EPUB转PDF/Word 的处理流程。

| 模式     | 图标  | 步骤                           | 输出    | 适用场景           |
| :------- | :---- | :----------------------------- | :------ | :----------------- |
| 产出PDF  | 📕-📖-⭕ | MD转EPUB → EPUB转PDF           | `.pdf`  | 已有正确公式的文档 |
| 产出PDF  | 📕-📖-📝 | 修复MD → 间转EPUB → EPUB转PDF  | `.pdf`  | 发布论文/报告      |
| 产出Word | 📄-📖-⭕ | MD转EPUB → EPUB转Word          | `.docx` | 已有正确公式的文档 |
| 产出Word | 📄-📖-📝 | 修复MD → 间转EPUB → EPUB转Word | `.docx` | 博客→Word文档      |
| 产出EPUB | 📖-📝-⭕ | 修复Markdown → 导出EPUB        | `.epub` | 博客→电子书        |

**核心技术**：流水线并行、哨兵对象模式、分步并行设置、中间/最终输出分离、YAML 标题重命名、配置键常量化统一管理。

### 📊 可视化监视面板（v1.16.0 增强版）

独立窗口，提供流水线的实时可视化追踪。快捷键 `Ctrl+Shift+M`。

- **实时状态同步**：主界面与监视面板双工执行，步骤状态跨会话保留
- **行独立配置**：每行可独立设置修复配置，覆盖全局配置
- **产物预览**：支持 MD/EPUB/PDF/Word 四种产物的系统默认应用预览
- **修复预览配置闭环**：从监视面板直接进入修复预览，调参后无缝写回独立配置
- **步骤回滚**：仅删除指定步骤产物，不影响下游文件
- **中间文件清理**：一键删除过程文件，只保留最终结果
- **日志跨会话保留**：详细日志支持保存、过滤、清空

### 📝 MD 公式修复 — 16项可配置修复

核心设计原则：**不勾选 = 不修复**。默认所有功能关闭，用户完全掌控。

- 🟢 **格式与语法修复**：多余换行清理、行内公式后添加空格、上下标范围修正、函数名正体化、矩阵末尾换行移除、括号配对检查、编码问题修复、美元符号转义
- 🟡 **语义增强**：Markdown符号转义、矩阵间添加乘号、移除尺寸命令
- 🔴 **高级转换**：`\bm`→`\vec` 转换、独立行内公式转块级
- 🛡️ **安全保护**：智能识别用户自定义命令、深度学习命令转文本
- 🖼️ **用户定制**：图片标题样式化（10种颜色方案）

**预览与调试体系**：批量预检摘要、并排对比预览、MathJax v3 离线渲染（缩放+换行）、快速调整面板累积式调试、配置更新一键同步。

### 📖 MD 转 EPUB — 精美排版电子书

基于 Pandoc + 自建 EPUB 打包器（EPUB 3.0 + NCX 兼容 EPUB 2.0）。

- **CSS 排版风格**：外部文件自动发现（朴素样式/简洁样式/暗色风格）
- **特色功能**：10种主题颜色、YAML 标题作为内部标题及重命名、Mermaid 图表渲染、智能精准打开输出目录

### 📕 EPUB 转 PDF — 多预设打印输出 + 页码

基于 Calibre `ebook-convert`，4种页边距预设（极限紧凑/左右紧凑/上下紧凑/对称装订），自定义字号，支持显示页码（底部居中浅灰色），多线程并行转换。

### 📄 EPUB 转 Word — 软回车修复与排版优化

基于 Calibre 转换，并内置强大的 **XML 级 DOCX 后处理引擎**，彻底解决 EPUB 转 Word 后的排版灾难。

| 功能             | 说明                                                         |
| :--------------- | :----------------------------------------------------------- |
| ✨ 软回车智能修复 | 自动将 Word 中的软回车(`^l`/`<w:br>`)拆分或合并为标准硬段落(`^p`/`<w:p>`)，彻底解决段落破碎、无法全选修改格式的问题 |
| 📄 页面尺寸预设   | 扁平化单选支持 A4 / Letter / B5 / A5                         |
| 🧠 离焦状态记忆   | 切换模块或关闭窗口时自动保存当前选项，下次进入无缝恢复       |
| 📂 智能打开目录   | 强制绝对路径化，彻底杜绝 Windows 下误跳"文档"文件夹的 Bug    |

### 🌐 全局交互与体验优化

- **智能打开目录**：全局修复 Windows 下因相对路径导致资源管理器误跳"文档"文件夹的顽固 Bug（覆盖 MD转EPUB / EPUB转PDF / EPUB转Word）
- **拖拽与粘贴**：热区扩大至整个 QGroupBox、Ctrl+V 粘贴导入
- **系统托盘**：后台运行 + 全局热键唤醒（`Ctrl+Shift+K`）
- **多实例控制**：防止多开导致的数据冲突
- **优雅关闭**：等待线程结束 + 超时强制终止，启动时自动清理残留临时目录
- **配置键常量化**：全模块统一使用 `config_keys.py` 管理配置键，消除魔法字符串
- **离焦自动保存**：所有模块切换或关闭窗口时自动保存当前 UI 状态

## 📖 使用示例

### 场景一：技术博客发布到知乎

1. 「📝 MD公式修复」→ 添加 `article.md`
2. 「🔧 高级设置」→ 选择「🟣 知乎发布」
3. 右键 →「🔍 预览此文件」→ 微调功能开关
4. 关闭预览 →「🚀 开始处理」
5. 输出 `article_fixed.md` → 发布到知乎

### 场景二：一键全流程输出 PDF + 监视面板追踪

1. 「🔄 组合工作流」→ 添加论文 `.md`
2. 选择「产出PDF：📕-📖-📝」模式，配置修复预设、EPUB风格、PDF页边距、页码
3. `Ctrl+Shift+M` 打开监视面板，点击「▶ 全部开始」实时查看进度
4. 完成后点击 👁 预览产物 → 🧹 清理中间文件

### 场景三：EPUB 转 Word 并修复破碎段落

1. 「📄 EPUB转Word」→ 拖入 `.epub` 电子书
2. 勾选「✨ 自动修复软回车 (↓ → ¶)」，选择页面尺寸 A4
3. 勾选「转换完成后自动打开输出目录」
4. 点击「🚀 开始处理」
5. 程序自动调用 Calibre 转换，并在底层重写 DOCX XML 树，将软回车完美拆分为硬段落。完成后精准弹出文件所在文件夹。

### 场景四：组合工作流输出 Word 文档

1. 「🔄 组合工作流」→ 添加博客 `.md`
2. 选择「产出Word：📄-📖-📝」模式
3. 在右侧「📄 Word 设置」中选择 A4 页面尺寸，勾选软回车修复
4. 点击「🚀 开始处理」
5. 自动完成 修复MD → 转换EPUB → 导出Word 全流程

## 🔧 实现原理

### 流水线并行架构

```
文件队列 → [步骤1: 修复] → Queue → [步骤2: 转EPUB] → Queue → [步骤3: 转PDF/Word]
    ↑          ↑ n workers          ↑ n workers          ↑ n workers
  file1     file1修复中          file1转EPUB中        file1转PDF/Word中
```

- **哨兵对象**：`_SKIP_SENTINEL`（失败传递）/ `_STOP_SENTINEL`（结束信号）
- **分步并行**：每个步骤可独立配置 worker 数量，CPU密集型步骤（修复）建议较少，IO等待型步骤（转换）可适当多开
- **中间/最终输出分离**：中间产物（`_fixed.md` / `.epub`）与最终产物（`.pdf` / `.docx`）分别管理，支持一键清理中间文件

### 全局路径解析防错机制

针对 Windows `explorer.exe` 对相对路径（如 `.`）默认回退到"文档"文件夹的行为，所有模块的 `_open_folder` 方法均强制调用 `Path.resolve()` 转换为绝对路径，从根源斩断 Bug。

## ⌨️ 快捷键一览

| 快捷键                 | 功能                                                | 作用域        |
| :--------------------- | :-------------------------------------------------- | :------------ |
| Ctrl+0/1/2/3/4         | 切换到工作流/MD转EPUB/EPUB转PDF/公式修复/EPUB转Word | 主窗口        |
| Ctrl+Shift+D           | 开始处理（当前模块）                                | 主窗口        |
| Ctrl+Shift+L           | 预检预览（默认第一个文件）                          | 主窗口        |
| Ctrl+Shift+M           | 打开监视面板（工作流模块）                          | 主窗口        |
| Ctrl+L                 | 显示/隐藏日志面板                                   | 主窗口/面板   |
| Ctrl+Q / Ctrl+Shift+Q  | 清空日志 / 清空文件列表                             | 主窗口        |
| Ctrl+K / Ctrl+Shift+K  | 切换托盘模式 / 从托盘唤醒                           | 主窗口 / 全局 |
| Ctrl+W                 | 退出软件 / 关闭修复预览 / 关闭监视面板              | 全局          |
| Ctrl+Left / Ctrl+Right | 预览中查看上一处/下一处变更                         | 预览          |
| Esc                    | 关闭修复预览并激活主窗口 / 关闭监视面板             | 预览/面板     |
| Delete                 | 删除文件列表中选中的文件 / 删除选中行               | 主窗口/面板   |
| Ctrl+V                 | 粘贴文件到监视面板                                  | 监视面板      |
| 双击托盘图标           | 从系统托盘唤醒窗口                                  | 托盘          |

## 🛠️ 依赖工具管理

帮助菜单 → 安装依赖工具 → 一键安装 Pandoc/Calibre/Node.js/Mermaid CLI

- 支持检测已安装工具的版本
- 支持在线更新到最新版本
- 提供各工具的卸载说明
- 通过 Windows 包管理器 (winget) 自动化安装

## ✅ 项目优点

- **功能独创性**：16项可配置公式修复 + 软回车 XML 级修复 + 并排对比预览 + 可视化监视面板 + 5种工作流模式
- **全链路闭环**：MD修复 → EPUB → PDF/Word 一键完成，实时追踪每步进度
- **架构设计优良**：`BaseModule` 模板方法 + 信号槽解耦 + CSS 外部配置化 + 统一状态管理 + 离焦自动保存 + 配置键常量化
- **极致体验**：全局修复"打开目录"Bug，彻底消除 Windows 用户的痛点；6套主题，拖拽导入
- **代码质量**：全模块配置键常量化，消除魔法字符串；流水线状态 key 归一化，避免状态分裂

## 📝 版本历史

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
