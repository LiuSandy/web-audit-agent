# WebAudit

WebAudit 是一个使用 Python、Playwright 和大语言模型的网站测试代理。它从目标页面发现站内链接，按“观察—思考—行动”循环操作页面，记录疑似问题，并可生成端到端测试。命令行提示、新生成的报告和测试说明默认使用简体中文；网址、选择器及浏览器原始错误保留原文。

## 功能

- **探索页面**：从起始网址收集同域名链接，建立待访问队列；模型根据页面元素决定跳转、点击和填写操作。
- **发现问题**：监控控制台错误、失败的网络请求、可见的表单校验提示，并支持破损图片检查和模型记录的功能、体验问题。
- **保存会话**：通过 SQLite 保存访问记录、待办队列和发现结果，支持恢复探索。
- **生成测试**：根据发现的问题生成 Python Playwright 端到端测试，可仅生成、顺序执行或并行执行。
- **输出报告**：在 `reports/` 中保存中文探索报告和测试执行报告；截图保存在 `reports/screenshots/`。

检测结果属于疑似问题。预期中的 4xx 响应、正常表单提示或第三方脚本错误也可能被记录，发布前应人工核实。

## 项目结构

| 路径 | 用途 |
|---|---|
| `src/index.py` | 交互式命令行入口 |
| `src/agents/` | 探索代理和单页测试代理 |
| `src/tools/` | 页面发现、错误监控、图片与布局检查 |
| `src/services/` | 模型接入、测试生成和执行 |
| `src/auth/` | 登录检测、凭据和会话管理 |
| `src/database/`、`src/repositories/` | SQLite 状态存储 |
| `src/mcp/` | MCP 标准输入输出服务 |
| `tests/`、`tests/test-resources/` | 自动化测试和测试页面 |
| `docs/`、`assets/` | 使用说明、设计文档和架构图 |

## 安装与配置

需要 Python 3.11.7 或更新版本，以及 uv。首次安装：

~~~bash
uv sync
uv run python -m playwright install chromium
cp .env.example .env
~~~

在 `.env` 中配置至少一个模型服务：`GOOGLE_AI_STUDIO_API_KEY`，或 `OPEN_AI_API_KEY`；使用兼容服务时可设置 `OPEN_AI_API_URL` 和 `OPEN_AI_MODEL`。不要提交 `.env`、`.auth.key`、SQLite 数据库、报告或生成的测试。

## 运行

启动交互式探索：

~~~bash
uv run python -m src.index
~~~

按提示输入目标网址、选择自主或人工引导模式、决定是否生成测试，并选择新建或恢复会话。结束后，探索报告写入 `reports/report-<session-id>.md`。

运行已有的生成测试：

~~~bash
uv run python -m src.cli.run-tests
uv run pytest generated-tests/broken-images/
~~~

启动 MCP 服务：

~~~bash
uv run python -m src.mcp.index
~~~

MCP 客户端配置、工具和资源见 [MCP 服务说明](docs/mcp-server.md)。`scripts/deploy-mcp.sh` 可创建指向同一 Python 入口的包装脚本。

## 开发与验证

~~~bash
uv run pytest
uv run ruff check src tests
~~~

`pyproject.toml` 定义 pytest 的 `*.test.py` 和 `*_spec.py` 发现规则；异步浏览器测试需要 Chromium。生成的测试位于 `generated-tests/<category>/`，使用 pytest 与 Python Playwright 运行。

## 设计说明

探索代理预先发现站内页面，再从简化的 DOM 快照和最近操作中选择下一步；每次跳转、点击或填写后执行自动错误检查。重复问题会合并，报告仍保留出现页面。单页测试代理采用“规划—执行”流程，并支持布局检查与可选的视觉差异检查。历史设计背景可参阅 `docs/`；实现以当前 `src/` 代码为准。
