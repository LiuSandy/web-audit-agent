# WebAudit

WebAudit 是一个使用 Python、Playwright 和大语言模型的网站测试代理。它从目标页面发现站内链接，按“观察—思考—行动”循环操作页面，记录疑似问题，并可生成端到端测试。命令行提示、新生成的报告和测试说明默认使用简体中文；网址、选择器及浏览器原始错误保留原文。

## 功能

- **探索页面**：从起始网址收集同域名链接，建立待访问队列；模型根据页面元素决定跳转、点击和填写操作。
- **发现问题**：监控控制台错误、失败的网络请求、可见的表单校验提示，并支持破损图片检查和模型记录的功能、体验问题。
- **保存会话**：通过 SQLite 保存访问记录、待办队列和发现结果，支持恢复探索。
- **生成测试**：根据发现的问题生成 Python Playwright 端到端测试，可仅生成、顺序执行或并行执行。
- **输出报告**：在 `~/.config/webaudit/data/runs/<session-id>/<run-id>/` 保存报告、截图和生成测试。

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
uv run webaudit config init
~~~

初始化会询问服务商、接口、模型和密钥，默认将密钥保存到系统凭据库。也可以直接设置 `OPENAI_API_KEY` 或 `GOOGLE_AI_STUDIO_API_KEY`。配置和数据统一存放在 `~/.config/webaudit/`，安装时不会创建目录。开发用 `.env` 需显式通过 `--env-file .env` 加载，不再自动搜索。目录、自定义路径、清理和卸载规则见 [CLI 配置与存储说明](docs/cli-storage.md)。不要提交密钥、数据库或运行产物。

## 运行

```bash
# 交互向导（无子命令时的默认入口）
uv run python -m src.index

# 非交互探索（脚本 / 跑批）
uv run python -m src.index run <url> --max-steps 10 --json

# 初始化与查看配置
uv run webaudit config init
uv run webaudit config show --sources
uv run webaudit paths

# 查看会话报告（可用 --run-id 指定历史运行）
uv run python -m src.index report --list
uv run python -m src.index report <session-id>

# 执行生成的 E2E 测试
uv run python -m src.index test

# 启动 MCP stdio server
uv run python -m src.index mcp

# 安装版（可选）：构建 wheel 并试用
uv build && uv tool install dist/*.whl && webaudit --version
```

运行交互向导（无子命令时的默认入口），按提示输入目标网址、选择自主或人工引导模式、决定是否生成测试，并选择新建或恢复会话。每次运行保留独立报告，路径为 `~/.config/webaudit/data/runs/<session-id>/<run-id>/report.md`，终端会显示绝对路径。

### 运行结果与恢复约定

`run --json` 的 stdout 只输出一个最终 JSON 对象，进度和错误走 stderr。运行失败、中断或模型初始化失败也会输出结果；参数校验失败在启动前返回标准用法提示。JSON 包含 `status`、`terminationReason`、`steps`（本次）、`sessionSteps`（累计）、`failedSteps`、`cleanupErrors`、`errors`、`reportPath`、`runId`、`artifactDir` 和 findings。

| 退出码 | 含义 |
|---|---|
| 0 | 正常结束或正常耗尽本次步数预算 |
| 1 | 运行、必要保存或清理失败 |
| 2 | 参数错误或恢复会话的目标站点冲突 |
| 130 | 用户中断；即使部分结果保存失败也保留此退出码，错误单独记录 |

`terminationReason` 为 `completed`、`step_limit`、`failed` 或 `cancelled`。`completed` 表示模型或用户正常结束，不代表已经遍历整个网站。达到步数上限时最后一步仍失败，则按失败处理。连续失败默认达到 3 步停止，可通过 `--max-failures N` 调整；成功动作会重置连续失败计数。动作结果会写入会话历史，供下一步模型参考。

`--max-steps N` 必须为正整数，表示**本次新增步骤预算**，恢复会话也遵循此约定。失败和中断时会尽量保存已有状态及标明运行结果的部分报告；保存错误会明确显示。可选测试生成失败只告警，不改变探索退出码。

恢复示例：

```bash
uv run python -m src.index run https://example.com --session-id <id> --max-steps 10 --json
```

会话保存起始 URL 和非敏感运行选项，恢复时校验协议、主机及端口，并采用本次命令的运行预算和测试选项。认证标识会自动复用，重新验证或恢复登录后再访问最后记录的页面；显式认证参数优先。密码保存在本地加密凭据库，不写入探索 state。旧会话从访问记录、历史或 findings 推导目标站点；无法推导时拒绝恢复，请新建会话。没有 findings 的新会话也可直接用 `report <id>` 重新生成报告。

MCP 客户端配置、工具和资源见 [MCP 服务说明](docs/mcp-server.md)。`scripts/deploy-mcp.sh` 可创建指向同一 Python 入口的包装脚本。

## 开发与验证

~~~bash
uv run pytest
uv run ruff check src tests
~~~

`pyproject.toml` 定义 pytest 的 `*.test.py` 和 `*_spec.py` 发现规则；异步浏览器测试需要 Chromium。生成的测试位于 `<data-dir>/runs/<session-id>/<run-id>/generated-tests/<category>/`，使用 pytest 与 Python Playwright 运行。

## 设计说明

探索代理预先发现站内页面，再从简化的 DOM 快照和最近操作中选择下一步；每次跳转、点击或填写后执行自动错误检查。重复问题会合并，报告仍保留出现页面。单页测试代理采用“规划—执行”流程，并支持布局检查与可选的视觉差异检查。历史设计背景可参阅 `docs/`；实现以当前 `src/` 代码为准。
