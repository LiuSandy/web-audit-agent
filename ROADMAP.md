# RoadMap

> 目标：把 WebAudit Agent 打磨成一个可靠、可观测、可评测的网站探索测试工具——稳定地发现真实问题，每次运行的效果可度量、行为可解释。
> 原则：每项改造都要能落成「新能力 + 可验证结果」，优先做能产生量化数据的。

## 总览

| # | 事项 | 优先级 | 状态 | 关键产出 |
|---|------|--------|------|----------|
| 1 | LangSmith 观测 | **P0** | ✅ 完成 | 每步 LLM 调用的 token/耗时/轨迹可视化 |
| 5 | 量化实验 | **P0** | ☐ 未开始 | 检出率 / 误报率 / 步数 / token 成本四项核心数字 |
| 2 | SEO 审计工具 | P1 | ☐ 未开始 | `src/tools/seo-audit.py` + Agent 新动作 |
| 3 | CLI 专业化 | **P0** | ✅ 完成 | 子命令 + flags + 非交互运行 + rich 输出 |
| 4 | 可视化改造 | P3 | ☐ 未开始 | HTML 报告（图表 + 截图 + 页面访问图） |

建议执行顺序：**3 → 5（首轮基线）→ 2 → 4**（#1 已完成）。优先级（用户指定，#3 于 2026-09-30 提为最高）：#5 量化实验建立基线，此后每完成一项重大改造复跑 #5，形成「改造前后」对比。#2 SEO 是快赢项，#4 依次靠后。

---

## 1. LangSmith 观测（P0）

**现状**：`src/services/llm.py` 用 langchain-core 创建模型；`exploratory.py:step()` 的 LLM 调用只有本地 logger，失败排障靠翻日志，token 消耗和延迟无量化手段。

**目标**：每次探索会话在 LangSmith 上形成一条完整 trace——每步的 prompt、模型输出、解析结果、动作执行结果、耗时、token 用量全部可查。

**任务**
- [x] 调研 langchain-core 的 tracing 接入方式（环境变量 `LANGSMITH_TRACING` / API key，或显式 callback）——结论：环境变量零侵入 + `langsmith.traceable` 装饰器组合
- [x] 配置项进 `.env.example`，代码零侵入优先（环境变量方案）
- [x] 给每步 trace 注入结构化 metadata：`sessionId`、`step`、`url`、`visitedCount`、`queueLength`
- [x] （加分）把 `execute_action`、`perform_automatic_bug_scanning` 作为子 run 上报，形成步骤级调用树——已实现：`agent.step → LLM 调用 / execute_action → automatic_bug_scanning` 三层树
- [x] 文档：`docs/observability.md` 记录接入方式与面板解读（面板截图待运行后补充）

**验收**
- 跑一次探索，LangSmith 面板能看到逐步 trace；能回答「这次会话花了多少 token、最慢的一步在哪」
- 由此得到第一批基线数字：单次会话平均 token 成本、平均步数、瓶颈定位（供 #5 使用）

---

## 2. SEO 审计工具（P1）

**现状**：`src/tools/` 已有 8 个检测工具，模式统一（注入 JS 回调返回结构化结果），但无 SEO 维度。

**目标**：新增 `audit_seo` 检测工具，并注册为 Agent 动作，让探索过程中自动发现 SEO 问题。

**任务**
- [ ] `src/tools/seo-audit.py`：照 `broken_images.py` 模式实现，注入回调检查：
  - [ ] `<title>` 缺失/过长/重复
  - [ ] meta description 缺失/过长
  - [ ] h1 数量 ≠ 1、标题层级跳跃
  - [ ] `img` 缺 `alt`、`html` 缺 `lang`
  - [ ] canonical / viewport / robots meta
- [ ] 定义 finding 类型与严重度映射（参照 `BROKEN_IMAGE_REASONS` 在 `src/utils/locale.py` 的做法）
- [ ] 注册动作：`_SYSTEM_PROMPT` 动作表 + `execute_action()` 分支 + 自动扫描管线（`perform_automatic_bug_scanning`）按需纳入
- [ ] MCP 侧同步暴露（`src/mcp/tools/definitions.py`）
- [ ] 测试：`tests/tools/seo-audit.test.py`（用 `tests/test-resources/` 的 fixture 页面）

**验收**
- 对 demo 站跑一次，报告中出现 SEO 类 finding 且无重复
- `uv run pytest tests/tools/seo-audit.test.py` 通过
- 覆盖 N 类 SEO 规则，规则清单与命中情况在报告中可核对

---

## 3. CLI 专业化（P0）

**当前状态**：typer 子命令、共享 runner、rich 输出与 JSON 模式已实现；运行失败、取消、清理和会话恢复契约已补齐。原先 questionary 逐条问询入口保留为默认交互向导。

**目标**：专业 CLI 的样子——子命令、参数、管道友好、rich 美化。`rich` 已在依赖里，直接用。

**任务**
- [x] 定参数框架（typer 或 argparse，倾向 typer：类型提示自动生成 help）
- [x] 子命令设计（草案）：
  - `run <url>`：非交互运行探索（`--autonomous --max-steps N --json`）
  - `report <session-id>`：按会话重新生成报告
  - `test`：等价现有 `src/cli/run_tests.py`，执行生成的 E2E 测试
  - `mcp`：启动 MCP server（等价 `src/mcp/index.py`）
  - 交互模式保留为无参数时的默认行为
- [x] rich 输出：spinner/status（`agent.start()` 阶段）、findings 表格、severity 着色
- [x] 退出码约定：0 成功 / 1 探索异常 / 2 参数错误（脚本化友好）
- [x] `--json` 输出模式：输出包含状态、终止原因、本次/累计步数、失败步数、报告路径和 findings 的单个 JSON 对象；诊断走 stderr
- [x] 异常路径：启动部分失败仍清理；模型/动作连续失败停止；报告与会话保存失败传播；中断尽量保存部分结果
- [x] 会话恢复：保存目标与非敏感配置、校验站点、复用认证标识并重新认证；兼容可推导站点的旧 state
- [x] 步数语义：正整数预算按本次运行计数；区分 completed / step_limit / failed / cancelled
- [x] 顺手清理：`wrap_text(str, ...)` 遮蔽内建 `str`（`src/index.py`）——importlib 手动加载 hyphen 模块的写法已随文件名规范化（2026-09-30）整体移除，无需再抽助手

**验收**
- `uv run python -m src.index --help` 输出规范用法
- `uv run python -m src.index run <url> --autonomous --max-steps 10` 全程无交互完成并出报告
- 同一会话可被脚本重复调用（会话恢复可用）

---

## 4. 可视化改造（P3）

**现状**：报告是纯 Markdown（`src/utils/report.py`），截图是独立 PNG 文件路径引用，问题分布、访问轨迹不可视。

**目标**：生成单文件 HTML 报告——打开即读，含图表、截图、探索轨迹。

**任务**
- [ ] 报告模板重构：`report.py` 抽出「数据收集层」，Markdown 与 HTML 两个渲染器共用
- [ ] HTML 报告内容（草案）：
  - 概览卡片：页面数 / 问题数 / 按类型·严重度分布
  - 严重度分布图、问题类型分布图（单文件内联实现，不引重框架）
  - 站点访问图：visitedUrls + todoQueue 关系（简单有向图，SVG 或 canvas）
  - 问题详情：描述、selector、截图内嵌（base64 或相对路径）、出现次数
  - 探索时间线：`state.history` 的动作序列
- [ ] CLI 增加 `report` 子命令后，支持按 session 历史数据重新出报告
- [ ] （依赖 #3 完成后）`run` 命令结束时自动生成 HTML 报告并在终端给路径

**验收**
- 单文件 HTML 离线可打开（无网络依赖），截图与图表正常渲染
- 同一份数据 Markdown 与 HTML 输出一致，无信息丢失

---

## 5. 量化实验（P0）

**现状**：Agent 效果没有任何数字支撑——检出能力、稳定性、token 成本、耗时均无测量手段，效果好坏无法判断，改造是否有效也无从验证。

**目标**：建立可重复的基准评测：固定条件跑 N 次，产出**检出率、误报率、平均步数、单次会话 token 成本**四个核心数字；此后每项重大改造复跑一轮，形成「改造前后」对比。

**任务**
- [ ] 人工整理 demo 站（with-bugs.practicesoftwaretesting.com）已知 bug 清单作为 ground truth，存 `docs/benchmark-ground-truth.md`
- [ ] 批量跑批脚本 `scripts/benchmark.py`：固定配置循环跑 N 次（同 maxSteps、同模型、独立会话），汇总每次的发现数、类型分布、步数、成败
- [ ] 接入 #1 的 token / 耗时数据（LangSmith 未就绪时，先出检出率与稳定性两个维度）
- [ ] 人工核对：findings 逐条标注「命中 ground truth / 真实但清单外 / 误报」
- [ ] 结果文档 `docs/benchmark-results.md`：数据表 + 每个数字的出处与样本量说明
- [ ] 固化流程：每完成一项 RoadMap 改造复跑一轮，结果文档追加「改造前后」对比列

**验收**
- `uv run python -m scripts.benchmark --runs 10` 一键跑完并输出汇总表
- 四个核心数字落表且有出处：检出率、误报率、平均步数、token 成本
- 完成至少一次「改造前后」A/B 对比（例如候选池的结构化输出约束改造）

**备注**
- 跑批脚本沉淀为项目的可重复评测基准（benchmark harness），供长期回归使用
- 模型输出有随机性，N=10 是起步值；引用结论时必须注明样本量
- ground truth 清单以 demo 站公开 bug 资料为主，人工核实为辅，清单本身也要注明版本日期

---

## 候选池（未排期）

之前讨论过的改进，做完上面五项后按需取用：

- 结构化输出约束：用模型 response schema 替代「markdown 围栏清洗 + json.loads」的脆弱解析（`exploratory.py:264`）
- 并发探索：todoQueue 串行 → `asyncio.gather` 多页面并发
- 可访问性（a11y）审计工具：与 SEO 工具同模式，成本极低

## 进度记录

| 日期 | 变更 |
|------|------|
| 2026-09-30 | 建立 RoadMap，四项初始事项 |
| 2026-09-30 | 量化实验从候选池提为正式任务 #5 |
| 2026-09-30 | 优先级调整（用户指定）：#1、#5 提为 P0，执行顺序改为 1 → 5 → 2 → 3 → 4 |
| 2026-09-30 | 目标定义调整：以项目本身为目标（可靠、可观测、可评测），文档表述统一为项目视角，TODO 不变 |
| 2026-09-30 | #1 LangSmith 观测实现完成：环境变量接入 + traceable 步骤级调用树（两个 Agent 均覆盖）+ docs/observability.md；新增单测 3 项，ruff 与全量 64 项测试通过。待配置 LANGSMITH_API_KEY 后做面板验证 |
| 2026-09-30 | #1 面板验证通过：3 条 agent.step trace 落库，metadata 与逐步延迟可见，任务正式完成；验证用临时脚本已删除 |
| 2026-09-30 | 模块文件名规范化：19 个连字符/点号命名的文件 `git mv` 为 snake_case（PEP 8），全部 importlib 动态加载改为普通 import（仅保留 mcp tools 内打破循环依赖的函数级延迟导入）；AGENTS.md 命名规范与 README/docs 中的路径、命令同步更新。ruff 通过，全量 64 项测试通过（1 项外部服务超时，重跑通过） |
| 2026-09-30 | 标识符命名规范化（PEP 8）：44 个文件、约 1260 处 camelCase 变量/函数/方法名批量改为 snake_case；类名保持 PascalCase，dict/JSON 键（MCP schema、state、LangSmith metadata、SQL）、内联 JS 与外部 API 参数（mimeType/includeAA 等）按契约保留。AGENTS.md 命名规范与 observability/ROADMAP 中的标识符引用同步更新。ruff 通过，全量 64 项测试通过（2 项 httpstat.us 外部超时，重跑通过），22 个模块 import 冒烟通过 |
| 2026-09-30 | 优先级调整（用户指定）：#3 CLI 专业化提为最高（P2 → P0），执行顺序改为 3 → 5 → 2 → 4（#1 已完成） |
| 2026-09-30 | #3 CLI 专业化实现完成：typer 子命令 run/report/test/mcp + 向导重写（rich 渲染、共用 runner）+ 退出码契约 0/1/2/130 + --json 输出 + hatchling 打包（uv build 可装）。src/cli/run_tests.py 由 test 子命令替代；wrap_text 遮蔽内建问题随旧向导消解。ruff 通过，全量 103 项测试通过 |
| 2026-10-02 | #3 异常路径与恢复契约补齐：保存失败传播、完整启动/清理生命周期、连续失败阈值、动作结果历史、结构化 JSON 结果、恢复目标及认证校验；新增失败边界与本地 Chromium CLI 集成验证；最终全量 152 项测试、Ruff 与 diff 检查通过。 |
