# RFC：通过 MCP 接入网站测试代理

> 历史设计文档。当前服务的启动方式与已实现接口见 [MCP 服务说明](mcp-server.md)；本提案中的资源、提示词或流式能力未必已实现。

**状态：**草案  
**作者：**Crisler Wintler  
**创建与更新：**2026-01-08

## 摘要

原提案希望通过 Model Context Protocol（MCP）将探索代理与单页测试代理开放给 IDE 和 AI 助手。开发者可在工作环境中启动测试、查询进度、停止会话和读取报告，不必只依赖独立的交互式 CLI。

## 背景与目标

MCP 使用客户端与服务端结构，通过 JSON-RPC 暴露工具、资源和可选的提示词模板：

- **工具**：启动或控制测试等可执行操作。
- **资源**：可读取的测试报告或状态数据。
- **提示词**：供客户端复用的测试任务模板。

接入目标是让测试能力可发现、可调用，并为长时间运行的测试提供会话 ID 与状态查询。原提案还讨论了进度通知和更多资源类型；当前实现以标准输入输出传输和已有工具为准。

## 架构

~~~mermaid
graph LR
    A[IDE 或 AI 助手] --> B[MCP 标准输入输出服务]
    B --> C[探索测试工具]
    B --> D[单页测试工具]
    B --> E[状态与会话工具]
    C --> F[探索代理]
    D --> G[单页代理]
    E --> H[会话状态]
    B --> I[报告资源]
    I --> J[Markdown 报告]
~~~

MCP 服务负责工具调用与资源读取；代理负责浏览器操作、模型规划和发现记录；SQLite 与报告文件保存状态及结果。工具返回稳定的 JSON 字段和值，并为面向用户的状态补充中文 `statusText` 或中文说明。

## 工具设计

| 工具 | 输入重点 | 返回或用途 |
|---|---|---|
| `run_exploratory_test` | `baseUrl`、`maxSteps`、`mode`、可选认证字段 | 启动多页面探索，返回 `sessionId` |
| `run_single_page_test` | `targetUrl`、`strategy`、`maxTestCases`、可选认证字段 | 启动单页测试，返回 `sessionId` |
| `get_test_status` | `sessionId` | 查询进度、当前操作与最近发现 |
| `stop_test` | `sessionId` | 请求停止会话 |
| `list_sessions` | `status`、`limit` | 列出运行中及已保存的会话 |

测试通常在后台执行，启动调用立即返回。客户端应保存 `sessionId`，之后按需查询状态。`status`、`priority` 等枚举是机器接口，不应为了翻译而改名；中文显示由额外字段或报告层提供。

## 资源与提示词提案

当前服务支持读取 `test-report://{sessionId}` 和 `test-report://latest`。资源处理器读取已有 Markdown，不自动生成报告。

原 RFC 还提出以下扩展，属于设计提案而非当前可用接口：

- `test-status://{sessionId}`：会话状态快照。
- `test-findings://{sessionId}`：发现列表。
- `test-plan://{sessionId}`：单页测试计划。
- `test-login-page` 和 `test-checkout-flow`：常见测试流程的提示词模板。
- 长任务的主动进度通知或流式更新。

客户端接入前应以服务实际列出的工具和资源为准。

## 配置示例

先在项目目录安装依赖及浏览器：

~~~bash
uv sync
uv run python -m playwright install chromium
uv run python -m src.mcp.index
~~~

Claude Desktop 可使用如下配置；将 `cwd` 替换为项目的绝对路径，并在本机安全地配置模型密钥：

~~~json
{
  "mcpServers": {
    "qa-agent": {
      "command": "uv",
      "args": ["run", "python", "-m", "src.mcp.index"],
      "cwd": "/absolute/path/to/web-audit-agent"
    }
  }
}
~~~

VS Code 等支持 MCP 的客户端可使用相应的 `command`、`args` 和 `cwd` 字段。标准输出属于 JSON-RPC 通道，调试日志应写入标准错误。

## 原提案的实施阶段

1. 建立 MCP 服务入口、协议处理与工具定义。
2. 实现探索测试、单页测试、状态、停止和会话列表工具。
3. 实现报告读取，并评估状态、发现与计划资源。
4. 提供客户端配置示例，验证后台执行、状态查询和错误处理。

## 安全与隐私

标准输入输出模式默认不暴露网络监听端口。API 密钥由本地环境提供；认证凭据和测试数据应按会话隔离。工具可能访问真实网站并产生报告，因此客户端调用应由用户明确发起。报告可能含 URL、响应内容或截图，不能假定只有公开信息；共享前应检查敏感数据。

## 权衡与后续问题

MCP 提供统一的工具发现和 IDE/助手接入，但增加了协议层、客户端配置及错误处理成本。继续保留 CLI 可支持独立使用。需要进一步评估多客户端并发隔离、长任务进度通知、资源缓存策略和代理异常后的恢复。原提案比较了 REST、gRPC 和 WebSocket，最终选择 MCP 以便与 AI 客户端集成。

## 参考

- [当前 MCP 使用说明](mcp-server.md)
- [当前 Python MCP 服务](../src/mcp/server.py)
- [MCP 官方站点](https://modelcontextprotocol.io/)
- [单页测试代理设计](rfc-single-page-testing-agent.md)
