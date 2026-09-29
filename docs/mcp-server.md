# MCP 服务接入

WebAudit 通过 Python 标准输入输出服务提供 MCP 工具和报告资源。工具名、输入字段、会话 ID 与报告 URI 是稳定的程序接口，保持英文标识。

## 启动

在项目目录执行：

~~~bash
uv sync
uv run python -m playwright install chromium
uv run python -m src.mcp.index
~~~

服务使用标准输入输出传输 JSON-RPC。标准输出仅用于协议消息；日志写入标准错误。

## 客户端配置

将 `cwd` 改为本机项目的绝对路径。Claude Desktop 配置示例：

~~~json
{
  "mcpServers": {
    "qa-agent": {
      "command": "uv",
      "args": ["run", "python", "-m", "src.mcp.index"],
      "cwd": "/absolute/path/to/web-audit-agent",
      "env": {
        "GOOGLE_AI_STUDIO_API_KEY": "在本机配置的密钥"
      }
    }
  }
}
~~~

VS Code 的 `servers` 配置可使用相同的 `command`、`args`、`cwd` 和 `env`。`scripts/deploy-mcp.sh` 会创建 `/tmp/qa-agent-mcp-wrapper.sh`，同样启动 Python 入口。

## 可用工具

| 工具 | 用途 |
|---|---|
| `run_exploratory_test` | 启动多页面探索测试 |
| `run_single_page_test` | 启动单页规划与执行测试 |
| `get_test_status` | 查询会话进度、状态和最近发现 |
| `stop_test` | 请求停止正在运行的测试 |
| `list_sessions` | 列出内存中及已保存的会话 |

测试在后台运行，启动调用会立即返回 `sessionId`。通过 `get_test_status` 查询进度。`status` 保留英文机器码；`statusText` 给出中文状态。单页测试同样返回中文进度与发现描述。

## 可用资源

| 资源 | 用途 |
|---|---|
| `test-report://{sessionId}` | 读取 `reports/report-{sessionId}.md` |
| `test-report://latest` | 读取 `reports/` 中最近的 Markdown 报告 |

资源处理器只读取已有文件，不负责生成报告。命令行探索结束时会生成报告；通过 MCP 启动的会话应按实际调用流程确认报告是否已创建。

## 主要实现文件

`src/mcp/index.py`、`src/mcp/server.py`、`src/mcp/tools/`、`src/mcp/resources/reports.py`、`src/agents/` 和 `src/repositories/session.repository.py`。
