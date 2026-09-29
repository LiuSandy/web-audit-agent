# WebAudit：TypeScript → Python 等价迁移方案

> 状态：Python 主体迁移已完成；2026-09-25 根据新增要求，将生成测试和运行器也改为 Python。下文保留初版等价迁移的决策记录，当前运行方式以“纯 Python 后续变更”一节为准。  
> 源项目：`/Users/lius/Desktop/self/agent-projects/qa-agent`（盘点基准提交 `c9cb81e`）。  
> 目标项目：`/Users/lius/Desktop/self/agent-projects/web-audit-agent`（编写方案时为空目录）。  
> 目标：将现有实现迁移到 Python，保持目录结构、文件名主体、类名和函数名，以及当前可观察行为；SEO 检查属于后续独立需求，不纳入本次迁移。

## 当前进度（2026-09-24）

- 已在目标目录执行 `uv init --bare`，使用 `uv add` 安装运行依赖、`uv add --dev` 安装测试依赖，生成 `pyproject.toml`/`uv.lock`。实际选用 CPython 3.13.12。
- 已逐一迁移 37 个 `src/*.ts` 为同路径主体名的 Python 文件，并逐一迁移 6 个测试文件；原有 `docs/`、`scripts/`、`assets/`、`.gemini/`、`test-results/` 和 `tests/test-resources/` 保留。`scripts/deploy-mcp.sh` 已改为启动 Python MCP 服务，README 命令已更新。
- 原 TypeScript 数据库测试 9 项通过；目标 Python 完整测试套件 53 项通过；TypeScript ↔ Python 双向读取 SQLite 会话和加密凭据通过；Ruff 检查通过。
- 固定本地网页及固定模型响应的探索式 Agent、单页 Agent、布局检查通过；MCP stdio 客户端的初始化、工具/资源清单和状态工具调用通过。Python 与 TypeScript `pixelmatch` 固定 PNG 样本的差异像素数、百分比和 diff 图像像素一致。
- 实测 `pytest-playwright` 与 `pytest-playwright-asyncio` 同时启用会冲突，目标项目只保留异步插件；下方安装命令已修正。
- Python 项目已经安装 Chromium；所有第三方 Python 依赖通过 `uv add` 管理。2026-09-25 起生成测试为 `*_spec.py`，由 uv 环境中的 pytest 执行。

## 1. 不可变约束及其可执行解释

1. **初始化和依赖管理**：在目标目录使用 `uv init`；所有新增第三方依赖仅通过 `uv add` / `uv add --dev` 写入 `pyproject.toml`，提交 `uv.lock`。不手工伪造锁文件，不使用 `pip install` 代替。
2. **目录名不变**：保留 `src/agents`、`src/auth`、`src/cli`、`src/database`、`src/mcp/resources`、`src/mcp/tools`、`src/repositories`、`src/services`、`src/tools`、`src/types`、`src/utils`、`tests/tools`、`tests/test-resources/test-app`、`docs`、`scripts`、`assets`；不改成 `web_audit/`、`app/` 等新目录。
3. **文件名不变的边界**：源码和测试文件仅把语言后缀 `.ts` 换成 `.py`，其余字符原样保留。例如 `single-page.ts → single-page.py`、`session.repository.ts → session.repository.py`、`auth.test.ts → auth.test.py`。HTML、图片、Markdown、Shell 文件保持原名。Python 工程元数据必须由 `package.json`/`bun.lock` 换成 `pyproject.toml`/`uv.lock`，这是工具链强制差异。
4. **标识符不变**：保留现有 `ExploratoryAgent`、`SinglePageTestingAgent`、`AppDatabase`、`handleRunExploratoryTest`、`generateReport`、`findBrokenImages` 等类/函数/方法名的大小写；不改为 snake_case。TypeScript 的 `constructor` 在 Python 中必须写作 `__init__`，这是语言特殊方法的唯一对应，不额外改业务方法名。匿名回调、类型接口的 Python 表达形式不视为业务函数重命名。
5. **逻辑不变的范围**：保留 Agent、身份验证、检测、数据库、报告与 MCP 的既有逻辑。用户于 2026-09-25 明确要求去除 Bun/Node 后，生成测试提示词、输出后缀和执行命令作为唯一明确授权的行为变更，见下文。
6. **品牌与行为分离**：项目元数据命名为 `web-audit-agent`，文档可称 WebAudit；现有 `qa-agent.sqlite`、`qa-agent-testing`、环境变量名、MCP URI、报告路径等运行时常量先保持不变。重命名这些常量属于另一个变更。

### Python 文件名的导入约束

`single-page.py`、`test-generator.py`、`auth-manager.py` 等含连字符；`session.repository.py` 含额外点号。它们不能写在普通 `from ... import ...` 语句的模块位置。实施时保留磁盘文件名，使用 `importlib.import_module()` 加载连字符模块；对 `session.repository.py` 使用 `importlib.util.spec_from_file_location()` 按路径加载并赋内部别名。模块内跨文件引用优先使用绝对导入，避免改变原文件名。可增加最少的 Python 包装/导入辅助代码，但不能移动业务实现或改公开类、函数和 MCP 名称。此前用 Python 3.9 实测 `importlib.import_module('a-b')` 可加载同名文件，点号文件可由 `spec_from_file_location` 定位；正式实施仍需在目标 Python 版本复测。

## 2. 源项目实际架构与迁移范围

当前共有 **37 个 `src/*.ts` 文件、6 个测试 `.ts` 文件**。入口是交互 CLI `src/index.ts`、生成测试运行器 `src/cli/run-tests.ts`、stdio MCP `src/mcp/index.ts`。探索代理为手写 Observe–Think–Act 循环；单页代理为 Plan–Execute 流程。`@langchain/langgraph` 虽声明依赖，但源码没有导入；不为迁移增加 LangGraph。`@langchain/community`、`@mozilla/readability`、`jsdom`、`zod` 同样没有源码导入，不列入首批 Python 依赖。

| 现有层 | 原文件 | 等价职责及迁移注意点 |
|---|---|---|
| Agent | `src/agents/exploratory.ts`, `single-page.ts` | 保留各自状态机、模型提示词、动作分支、扫描时机和停止语义；浏览器调用改为 Python Playwright 异步 API。 |
| 浏览器工具 | `src/tools/*.ts`（9 个） | DOM 检查、console/network 事件、爬取、截图、布局与视觉回归。`page.evaluate` 中的网页 JavaScript 可保留原脚本逻辑，Python 只替换调用宿主。 |
| 身份验证 | `src/auth/*.ts`（7 个） | 登录检测/执行、TOTP、凭据优先级、浏览器会话恢复；维持凭据表和现有加密数据可读。 |
| 状态/报告 | `src/database/database.ts`, `src/repositories/session.repository.ts`, `src/utils/*.ts` | 原 SQLite 三表、Set 的 JSON 编码、Markdown 内容及路径不变。 |
| 模型/生成测试 | `src/services/*.ts`（3 个） | 保留模型选择优先级、模型默认值、提示词、分类、生成文件名、重试/并行/超时策略。 |
| MCP | `src/mcp/**/*.ts`（9 个） | 保留 5 个工具名、参数 schema、`test-report://` 资源、stdio 传输和后台返回 `sessionId` 的形式。 |
| CLI/测试 | `src/index.ts`, `src/cli/run-tests.ts`, `tests/**/*.ts` | 保留交互选项、默认值、测试场景和断言；仅换 Python 运行/测试框架。 |

### 全量路径映射（`src`）

```text
src/agents/exploratory.ts              → src/agents/exploratory.py
src/agents/single-page.ts              → src/agents/single-page.py
src/auth/auth-manager.ts               → src/auth/auth-manager.py
src/auth/credential-provider.ts        → src/auth/credential-provider.py
src/auth/credential-storage.ts         → src/auth/credential-storage.py
src/auth/login-detector.ts             → src/auth/login-detector.py
src/auth/login-executor.ts             → src/auth/login-executor.py
src/auth/mfa-handler.ts                → src/auth/mfa-handler.py
src/auth/session-manager.ts            → src/auth/session-manager.py
src/cli/run-tests.ts                   → src/cli/run-tests.py
src/database/database.ts               → src/database/database.py
src/index.ts                           → src/index.py
src/mcp/index.ts                       → src/mcp/index.py
src/mcp/resources/reports.ts           → src/mcp/resources/reports.py
src/mcp/server.ts                      → src/mcp/server.py
src/mcp/tools/definitions.ts           → src/mcp/tools/definitions.py
src/mcp/tools/exploratory.ts           → src/mcp/tools/exploratory.py
src/mcp/tools/sessions.ts              → src/mcp/tools/sessions.py
src/mcp/tools/single-page.ts           → src/mcp/tools/single-page.py
src/mcp/tools/status.ts                → src/mcp/tools/status.py
src/mcp/types.ts                       → src/mcp/types.py
src/repositories/session.repository.ts → src/repositories/session.repository.py
src/services/llm.ts                    → src/services/llm.py
src/services/test-executor.ts          → src/services/test-executor.py
src/services/test-generator.ts         → src/services/test-generator.py
src/tools/broken-images.ts             → src/tools/broken-images.py
src/tools/console-errors.ts            → src/tools/console-errors.py
src/tools/crawler.ts                   → src/tools/crawler.py
src/tools/layout-audit.ts              → src/tools/layout-audit.py
src/tools/network-errors.ts            → src/tools/network-errors.py
src/tools/screenshot.ts                → src/tools/screenshot.py
src/tools/validation-errors.ts         → src/tools/validation-errors.py
src/tools/visual-regression.ts         → src/tools/visual-regression.py
src/types/index.ts                     → src/types/index.py
src/utils/helpers.ts                   → src/utils/helpers.py
src/utils/logger.ts                    → src/utils/logger.py
src/utils/report.ts                    → src/utils/report.py
```

测试路径逐一映射：`tests/auth.test.ts → tests/auth.test.py`、`tests/database.test.ts → tests/database.test.py`、`tests/tools/{broken-images,console-errors,network-errors,validation-errors}.test.ts → 同路径同主体 .test.py`。`tests/test-resources/test-app/{login.html,dashboard.html,README.md}` 原名复制。`docs/*.md`、`assets/llm-arch.png`、`scripts/deploy-mcp.sh`、`.env.example`、`README.md`、`AGENT.md`、`CHANGELOG.md` 均保留路径与文件名，允许文档/脚本内部命令换为 Python/uv。原仓库跟踪的 `test-results/trace.zip` 也按原路径复制，以满足严格文件名一致要求；运行时生成的 `reports/`、`generated-tests/`、SQLite、密钥、缓存和浏览器下载不复制。

## 3. 初始化及依赖安装命令

目标目录目前为空；实施时在目标目录执行，不能在源项目中执行。`--bare` 避免 uv 自动创建 `main.py`/`README.md` 等破坏文件名约束的模板文件；`--no-workspace` 防止意外加入父目录工作区。

```bash
cd /Users/lius/Desktop/self/agent-projects/web-audit-agent
uv init --bare --name web-audit-agent --no-workspace .

# 仅添加源码实际需要的 Python 运行依赖；具体版本由 uv.lock 固定
uv add playwright langchain-core langchain-openai langchain-google-genai mcp \
  cryptography pyotp pillow numpy questionary rich python-dotenv pixelmatch

# 仅添加迁移测试与静态检查需要的开发依赖
uv add pytest
uv add --dev pytest-asyncio pytest-playwright-asyncio ruff

# 独立安装浏览器二进制，uv add 不会代替这一步
uv run python -m playwright install chromium
```

项目目前选用 CPython 3.13.12，`pyproject.toml` 保留 Python 3.11.7 或更高的版本要求；`uv.lock` 保留为可重现安装依据。

依赖对应关系：

| TypeScript / Bun | Python | 保持行为的要求 |
|---|---|---|
| `playwright-core` | `playwright.async_api` | 保持 Chromium、viewport、timeout、等待状态、事件订阅和截图参数。 |
| LangChain Core/OpenAI/Google | `langchain-core`、`langchain-openai`、`langchain-google-genai` | 保持 Gemini 优先、OpenAI 兼容回退、原环境变量和模型默认值；对齐消息内容提取、超时与重试。 |
| MCP TS SDK | 官方 `mcp` | 保持原工具/资源定义和 stdio JSON-RPC 形状；不要借迁移改变任务状态模型。 |
| `bun:sqlite` | 标准库 `sqlite3` | 表结构、主键、时间戳、SQL、文件名和 JSON 编解码保持兼容。 |
| Node `crypto` AES-256-CBC | `cryptography` | 保持 32 字节密钥、16 字节 IV、PKCS#7 填充、hex 存储及 `.auth.key` 读取顺序；不要换成新的密文格式。 |
| `otplib` | `pyotp` | 通过相同 secret 和固定时刻校验生成码一致。 |
| `pngjs` + `pixelmatch` | Pillow + Python `pixelmatch` | 保持像素阈值、差异百分比、尺寸不匹配和 diff 图行为；不能直接以简单数组差异替代 pixelmatch 算法。 |
| `@clack/prompts` / `adze` | `questionary` + `rich` / 标准库 `logging` | 菜单项、默认值、取消路径和进度语义保持一致。 |
| Bun 自动读取 `.env` | `python-dotenv` | 保持同名环境变量以及“仅在未由进程环境提供时才使用 `.env`”的优先级。 |

### 生成测试的初版兼容决策（已由后续要求替代）

初版为保持与源项目一致，生成 `.spec.ts` 并使用 Bun/Node 执行。用户随后明确要求 Python 项目不再依赖该工具链；当前实现改为生成 `*_spec.py`，使用 Python Playwright 与 pytest。保留此段仅说明迁移决策的时间顺序，当前命令见 `docs/test-writing-capability.md`。

## 4. 分阶段实施顺序与每阶段验收

### 阶段 0：冻结源项目基线

- 记录源提交、`package.json`/`bun.lock`、`.env.example`、全部文件与公开标识符清单；源仓库只读。
- 使用相同浏览器版本、固定本地测试页、固定模型响应或 mock，采集探索动作序列、单页计划与结果、MCP 请求响应、SQLite 数据、报告文本和生成测试文件名。真实 LLM 输出不确定，差异对比必须采用固定响应。
- 记录当前环境缺失 Playwright Chromium 和测试端口冲突等环境阻塞；先消除环境差异，再建立可比较基线。当前源码的类型错误、单页动作异常吞吐、MCP 单页状态/报告问题记录为“既有行为”，迁移中不修复。

### 阶段 1：项目骨架与类型/数据层

- 执行第 3 节 `uv init`、`uv add`。按第 2 节创建同名目录和 `.py` 文件；先建立 `src/types/index.py` 的等价数据结构。字段名保持 camelCase，不能因 dataclass/Pydantic 默认命名改变外部 JSON。
- 移植 `AppDatabase`、`SessionRepository`、`CredentialStorage`、`SessionManager`。保持 3 张表、SQL、数据库文件名 `qa-agent.sqlite`、日期字段单位（秒或毫秒依原实现）和 Set 的 `{"_type":"Set","values":[...]}` 格式。
- 验收：旧 SQLite 可读；原密钥与凭据可解密；Python 写入的新数据可由原实现读取。对比空库建表 SQL、会话保存/恢复、凭据优先级和 24 小时会话过期边界。

### 阶段 2：浏览器工具与身份验证

- 逐文件移植 `src/tools/*.ts` 与 `src/auth/*.ts`；把 `page.evaluate` 函数转成等价的浏览器端 JS 字符串，保持选择器、滚动、过滤、严重级别、截图路径和事件收集时机。
- 视觉回归单独做固定 PNG 样本对照：相同尺寸、尺寸不一致、阈值边界、透明度/抗锯齿、diff 图。不能把差异扩大解释为“Python 实现不同”。
- 验收：同一组本地 HTML 页面下，检测结果字段、数量、顺序一致；登录检测、TOTP、Cookie/localStorage 恢复一致。

### 阶段 3：模型服务与两个 Agent

- 移植 `src/services/llm.py`，保持配置优先级、环境变量名、默认模型、温度、输出限制和失败信息；以固定响应替身验证，而不把真实模型波动当代码差异。
- 移植 `ExploratoryAgent` 和 `SinglePageTestingAgent` 的全部原方法，保持提示词原文、JSON 清理规则、30 秒模型超时、429 重试、爬取上限、`maxSteps`/`maxTestCases`、自动扫描时机、报告调用和停止条件。Python `asyncio` 任务的生命周期只用于承载原异步语义。
- 验收：同一初始状态与固定模型响应下，浏览器动作序列、状态保存点、发现列表、单页测试结果相同。当前“点击等异常被吞掉”“verify 不执行断言”等既有行为仍需保持，并写入对照测试。

### 阶段 4：CLI、MCP、报告与生成测试

- 移植 `src/index.py`、`src/cli/run-tests.py`、`src/mcp/**/*.py`、`src/utils/report.py`。MCP 保持 `run_exploratory_test`、`run_single_page_test`、`get_test_status`、`stop_test`、`list_sessions` 这 5 个名称、输入 schema、返回 JSON 字段、`test-report://latest` 与 `test-report://{sessionId}`。
- 保持 CLI 现有选项和默认值以及报告结构；生成测试的格式、提示词和调用命令按用户后续要求改为 Python。`scripts/deploy-mcp.sh` 启动同名 Python MCP 入口。
- 验收：用 MCP 客户端依次调用 5 个工具与两个资源，比较工具列表、资源列表、正常返回和错误返回；CLI 走新建/恢复、手动/自动、正常/取消路径。

### 阶段 5：测试迁移及交付门槛

- 按原测试文件名主体移植 6 个测试文件，保留测试场景和断言；用 `pytest` 配置识别 `*.test.py`，不要重命名为 `test_*.py`。测试用静态 HTML 保留原样。若 `pytest` 的导入机制与连字符/点号文件冲突，仅调整测试加载配置或使用 `--import-mode=importlib`，不改测试文件名。
- `uv run pytest`、`uv run ruff check`、源/目标等价对照、CLI/MCP 冒烟、数据库双向兼容和报告/生成文件对照全部通过后，才视为迁移完成。测试环境必须安装 Chromium，并处理源测试固定端口 `8889` 的占用；不要把环境失败统计为逻辑差异。
- 对每个差异给出“源行为、Python 行为、证据、是否符合不改逻辑”的记录。无法等价的行为不得静默放行；保持源行为或提交单独变更请求。

## 5. 明确不做的事

- 不增加 SEO 检查、性能指标或新的 Agent 框架；这些需求在等价迁移完成后再实施。
- 不把 `single-page.py` 等改成蛇形文件名；不把 camelCase 方法改成 snake_case。
- 不重写提示词、判定规则、异常处理、严重级别、报告结构或数据库加密格式。
- 不把已知缺陷混入迁移修复；先以对照测试保留，再另行修复。

## 6. 关键风险与决策记录

| 风险 | 处理方式 |
|---|---|
| Python 导入语法不接受现有连字符/点号文件名 | 使用 `importlib` 路径加载；文件名约束优先，文档化加载方式并单独验证。 |
| 完全 Python 化与初版“生成 TS 测试且不改变逻辑”相冲突 | 用户后续明确要求去除 Bun/Node，现已改为 `*_spec.py`、Python Playwright 与 pytest。 |
| 不同语言的默认真值、JSON、日期、正则、异常、并发语义 | 逐分支迁移，使用固定输入/固定时钟/固定模型响应做契约对照；必要时做局部兼容翻译，不改判断结果。 |
| `pixelmatch` 与 Pillow/NumPy 的结果可能不一致 | 移植原比较算法并做像素级固定样本对照。 |
| 旧 SQLite/密钥与新 Python 数据不兼容 | 在旧库副本上验证读写；不直接修改生产会话库。 |
| 现有测试无法全部运行 | 先安装浏览器并处理端口，再冻结基线；记录环境阻塞，不根据失败结果推断产品逻辑。 |

## 7. 资料依据

- 源项目：`package.json`、`src/` 全部 37 个 TypeScript 文件、`tests/` 6 个 TypeScript 测试、`.env.example`；重点核查 `src/agents/`、`src/services/test-generator.ts`、`src/services/test-executor.ts`、`src/mcp/`、`src/database/database.ts`。
- uv 官方文档：<https://docs.astral.sh/uv/concepts/projects/init/>、<https://docs.astral.sh/uv/concepts/projects/dependencies/>；本机 `uv 0.11.18` 的 `uv init --help`、`uv add --help` 核对了命令参数。
- Playwright Python 官方文档：<https://playwright.dev/python/docs/library>、<https://playwright.dev/python/docs/test-runners>。
- MCP Python 官方 SDK：<https://github.com/modelcontextprotocol/python-sdk>；支持 tools/resources 与 stdio transport。

## 8. 本次实施验证记录

- 路径检查：源项目 37 个 `src/*.ts` 与目标项目 37 个 `src/*.py` 一一对应；6 个测试文件一一对应；除 Python 工具链必须替换的 `package.json`、`bun.lock`、`tsconfig.json` 外，原项目受版本控制的路径均在目标项目存在。原项目工作树保持干净。
- `uv run pytest -q`：53 passed。浏览器用例使用本地 Chromium；网络监控测试沿用原测试中的外部 URL。
- `ruff check --no-cache src tests`：通过。Ruff 规则限定为基础语法、未使用变量等检查，因为源项目要求保留部分广泛捕获异常与静默忽略分支。
- 固定本地网页与固定模型响应：`ExploratoryAgent.start/step/stop`、`SinglePageTestingAgent.start`、布局检查、完整登录流程、浏览器会话保存均通过。
- MCP stdio：客户端初始化、5 个工具清单、2 个资源清单、`get_test_status` 调用通过；`scripts/deploy-mcp.sh` 生成的 wrapper 路径也通过客户端连接。
- 生成测试：初版曾确认提示词逐字符一致并执行旧生成格式；2026-09-25 起由下方纯 Python 验收结果替代。
- 视觉回归：同一固定 PNG 样本的原 TypeScript `pixelmatch` 与 Python `pixelmatch` 得到相同差异像素数、百分比和 diff 图像像素。
- SQLite 会话与加密凭据：原 TypeScript 与目标 Python 双向读取通过。
- 未使用真实 LLM API 或外部目标站点做端到端验证；这些结果依赖用户的 API 密钥、网络与目标站点状态。迁移验证采用固定模型响应及本地网页以排除外部波动。

## 9. 纯 Python 后续变更（2026-09-25）

用户明确要求 Python 项目不再有 Bun/Node 技术栈。这项要求覆盖初版对生成测试格式与执行命令保持不变的限制。当前 `TestGenerator` 只接受含有顶层 `test_` 函数的有效 Python，生成 `generated-tests/<category>/e2e-<date>-<n>_spec.py`；`TestExecutor` 使用当前 Python 解释器运行 `pytest`，保留 dry-run、顺序/并行、超时和重试选项；交互式测试 CLI 也运行 pytest。项目以 `uv`、Python Playwright、pytest 为唯一命令行运行栈。历史 RFC 与变更日志中提到的旧技术仅是源项目记录，不代表当前依赖。

- `pytest` 已通过 `uv add` 移入运行依赖；浏览器测试所需的 `pytest-asyncio` 和开发期 Ruff 留在开发依赖。
- 固定模型响应、临时本地 HTML 和 Chromium 的生成→保存→执行→CLI 批量执行验证通过；无效 Python 或没有顶层 `test_` 的输出会被拒绝。
- 更新后的完整回归在临时工作副本中通过（55 个项目测试，加 1 个临时生成文件）；`testpaths = ["tests"]` 确保日常 `pytest` 只跑项目测试。Ruff 检查通过。项目测试共 55 项。
