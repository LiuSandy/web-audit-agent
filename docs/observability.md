# 可观测性：LangSmith 接入指南

WebAudit Agent 通过 [LangSmith](https://smith.langchain.com) 记录每次探索会话的完整调用轨迹：每一步的 prompt、模型输出、动作执行结果、耗时与 token 用量。这些数据是量化实验（RoadMap #5）中成本与性能指标的来源。

## 前置条件

1. 注册 [smith.langchain.com](https://smith.langchain.com)（免费个人版即可，每月 5000 条 trace 额度）。
2. 在 **Settings → API Keys** 创建 Personal Access Token，复制备用。

## 配置

在项目根目录 `.env` 中添加：

```bash
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=lsv2_pt_xxxxxxxxxxxx
LANGSMITH_PROJECT=web-audit-agent
```

| 变量 | 说明 |
|------|------|
| `LANGSMITH_TRACING` | 总开关。`true` 时所有 LLM 调用与被装饰的 Agent 方法自动上报；不设置或 `false` 时完全关闭，零额外行为 |
| `LANGSMITH_API_KEY` | 上一步创建的 API key |
| `LANGSMITH_PROJECT` | 面板中的项目名，建议保持 `web-audit-agent` |
| `LANGSMITH_ENDPOINT` | 可选，默认 `https://api.smith.langchain.com`，自托管时才需要改 |

配置由 `python-dotenv` 在 `src/services/llm.py` 导入时加载，无需改动任何代码。

## 面板中能看到什么

每次运行后打开 smith.langchain.com，进入 `web-audit-agent` 项目 → **Traces**：

### 探索式测试（ExploratoryAgent）

```
agent.step                      ← 每个探索步骤一条，metadata 含 sessionId/step/url/visitedCount/queueLength
├── ChatGoogleGenerativeAI      ← 该步的 LLM 决策调用（prompt、补全、token 数、延迟）
└── execute_action              ← 动作执行（navigate/click/fill_form 等），inputs 含 action 与参数
    └── automatic_bug_scanning  ← 每次导航/点击后触发的自动问题扫描（console/network/validation）
agent.generate_tests            ← 测试生成会话（findings → E2E 测试），内含其 LLM 调用
```

### 单页测试（SinglePageTestingAgent）

```
single_page_test                ← 整个单页测试会话
├── single_page.plan            ← 测试计划生成，内含规划 LLM 调用
└── single_page.test_case       ← 每个测试用例的执行，inputs 含完整用例定义
```

### 常用排查视角

- **成本视角**：Traces 列表切换到按 token 排序，定位消耗最大的步骤。
- **延迟视角**：展开某条 `agent.step`，比较 LLM 调用与动作执行的耗时占比。
- **失败视角**：`agent.step` 上报的 `error` 状态对应模型调用失败或 JSON 解析失败。

## metadata 字段对照

`agent.step` 每条 trace 携带以下 metadata（由 `src/agents/exploratory.py` 的 `build_step_metadata` 生成；键名为 LangSmith metadata 契约，保持 camelCase）：

| 字段 | 含义 |
|------|------|
| `sessionId` | 探索会话 ID，用于在面板按会话过滤 |
| `step` | 当前探索步数（从 1 开始） |
| `url` | 本步开始时的页面 URL |
| `visitedCount` | 已访问页面总数 |
| `queueLength` | 待办队列剩余页面数 |

## 实现说明

- 基线 tracing 由 langchain-core 的环境变量机制自动完成，模型调用零侵入。
- Agent 内部方法（`agent.step`、`execute_action` 等）使用 `langsmith.traceable` 装饰器上报为子 run，与 LLM 调用组成调用树。
- 关闭 tracing 时装饰器仅多一次开关检查，不产生网络请求，行为不变。

## 隐私提示

Trace 包含完整 prompt 与页面快照内容（含目标站的 DOM 结构、元素文本），将发送至 LangChain 云端。请勿对包含敏感数据的内部系统开启 tracing，或在自托管 LangSmith 上运行。
