# 贡献指南

首先，感谢你考虑为 MicroBlog 做出贡献！这份指南旨在帮助你顺利地参与项目，无论你是报告 Bug、提出新功能，还是提交代码。

## 如何报告 Bug

如果发现 Bug，请在 GitHub Issues 中新建一个 Issue，并尽量包含以下信息：

- **简要描述**：清晰简洁地描述问题。
- **复现步骤**：详细的操作步骤，包括使用的版本和配置。
- **预期行为**：你希望看到什么结果。
- **实际行为**：实际发生了什么，如有错误截图或日志请一并贴上。
- **环境信息**：
    - MicroBlog 版本（tag）或 commit hash
    - Python 版本
    - Flask 版本（见 `requirements.txt`）
    - 数据库类型（SQLite / MySQL）及版本

## 如何提出新功能或改进

在提出新功能前，建议先搜索已有 Issue，避免重复。提交新功能建议时，请说明：

- **这个功能解决了什么痛点？** 描述你在实际场景中遇到的问题。
- **你的建议方案是什么？** 尽量具体，如果可能，描述你设想的 API 或界面交互方式。
- **影响范围**：是否会涉及现有路由、数据模型、模板或 i18n 翻译？

## 代码贡献流程

### 1. 沟通先行
如果你打算实现一个较大的功能或重构，请**先在 Issue 中讨论**，确保你的方向与项目维护者一致，避免投入大量精力后方案被拒绝。

### 2. 准备开发环境
- 确保已安装 **Python 3.10+**（推荐 3.11）和 **pip**。
- Fork 本仓库，并将你的 Fork 克隆到本地。
- 创建并激活虚拟环境：
  ```bash
  python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
  ```
- 运行 `pip install -r requirements.txt` 安装依赖。
- 复制 `.env.example` 为 `.env`，根据本地环境修改配置。
- 使用 `python run.py` 启动开发服务器（默认 SQLite，生产环境可选 MySQL）。

### 3. 编写代码
- **代码风格**：Python 代码遵循 **PEP 8**，并通过 **ruff** 检查。提交前请运行 `ruff check app config.py run.py tests`。
- **测试**：在 `tests/` 中为新功能或修复编写相应测试，并确保现有测试全部通过：`pytest`（135+ 项）。
- **前端**：模板位于 `templates/`，静态资源位于 `static/`。新增 JS/CSS 必须本地化（不使用 CDN），并遵循现有的玻璃拟态主题体系（`static/css/themes.css`、`static/js/theme-switcher.js`）。
- **文档**：你的贡献必须包含或更新相关文档，包括：
    - 更新 `README.md` / `README_ZH-CN.md` 中的使用说明。
    - 如果新增界面文案，请同步更新 `messages.pot` 与 `translations/` 下的 `.po` 文件。
    - 如果引入新的配置项，请更新 `.env.example` 和管理员手册。

### 4. 提交代码（Commit Message）

请使用清晰、描述性的提交信息。
强烈建议遵循 **Conventional Commits** 规范：

    <类型>(可选范围): <简短描述>

    <可选的详细描述>

- **常用类型**：
  - `feat`: 新功能
  - `fix`: Bug 修复
  - `docs`: 文档变更
  - `style`: 代码格式（不影响功能）
  - `refactor`: 重构（不是新功能也不是修 Bug）
  - `test`: 增加或修改测试
  - `chore`: 构建过程或辅助工具的变动

**示例**：

    feat(blog): 增加文章按分类归档功能

    新增按分类聚合文章的路由，
    更新侧边栏查询层并补充相关测试。

### 5. 发起 Pull Request (PR)

- 确保你的 PR 基于最新的 `main` 分支（或 `release/x.y.z` 分支）。
- 在 PR 描述中，清晰说明解决了什么问题，并关联相关的 Issue（如 `Closes #123`）。
- 确保 CI（ruff + pytest）检查通过，且分支没有冲突。

## 行为准则

本项目的参与者应遵守 [贡献者公约](https://www.contributor-covenant.org/zh-cn/version/2/0/code_of_conduct/)。我们期望所有互动都是开放、包容和尊重的。

## 获取帮助

如果你在贡献过程中有任何疑问，欢迎在 Issue 中提问，或通过邮件联系维护者（jeanslw@qq.com）。

再次感谢你的贡献！
