# Python / Flask 项目 AI 协作规范

## 语言与框架
- Python 3.10+（目标版本 3.11，见 pyproject.toml）
- Flask 3.1 + Flask-SQLAlchemy / Flask-WTF / Flask-Login / Flask-Babel
- 依赖版本锁定在 requirements.txt，不得随意升级大版本
- 代码风格与静态检查由 ruff 统一（配置见 pyproject.toml `[tool.ruff]`）

## 命名规范
- 函数/变量：snake_case
- 类：PascalCase
- 常量：UPPER_SNAKE_CASE
- 数据库表/字段：snake_case
- URL 路径：kebab-case（Flask 端点命名使用 snake_case）

## 安全红线
- 禁止 eval()、exec()、pickle 反序列化不可信数据
- 用户输入必须校验/转义；数据库查询必须参数化（Flask-SQLAlchemy 默认）
- 文章正文 HTML 必须经过 nh3 白名单净化后再标记 `|safe` 渲染
- 敏感配置（SECRET_KEY、数据库密码）必须走环境变量，禁止硬编码

## 回答纪律
- 不确定时说"我不确定，建议查阅官方文档"
- 不得虚构不存在的函数/类/包
- 给出的代码片段必须标注适用的 Python/Flask 版本
- 代码改动后用 `ruff check` 与 `pytest` 验证

## 提交推送

- 用户在没有让你提交和推送时，不要自作主张
- 不确定要不要提交，先征求用户意见
- 提交时要推送哪几个平台，征求用户意见
- 怎么推送，用户会给一个完整的意见
