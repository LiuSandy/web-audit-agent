"""MCP stdio server exposing WebAudit tools and resources."""

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.shared.exceptions import MCPError

from src.mcp.resources.reports import handleTestReportResource
from src.mcp.tools.definitions import TOOL_DEFINITIONS
from src.mcp.tools.exploratory import handleRunExploratoryTest
from src.mcp.tools.sessions import handleListSessions
from src.mcp.tools.single_page import handleRunSinglePageTest
from src.mcp.tools.status import handleGetTestStatus, handleStopTest
from src.utils.logger import createLogger

logger = createLogger("mcp-server")
activeTests = {}


class TestingAgentMCPServer:
    def __init__(self):
        self.server = Server("qa-agent-testing", version="1.0.0",
            on_list_tools=self._on_list_tools, on_call_tool=self._on_call_tool,
            on_list_resources=self._on_list_resources,
            on_read_resource=self._on_read_resource)
        self.setupHandlers()

    def setupHandlers(self):
        return None

    async def _on_list_tools(self, context, params):
        return types.ListToolsResult(tools=[types.Tool(**definition) for definition in TOOL_DEFINITIONS])

    async def _on_call_tool(self, context, params):
        toolName = params.name
        args = params.arguments or {}
        logger.info(f"调用工具：{toolName}，参数：{args}")
        try:
            if toolName == "run_exploratory_test":
                result = await handleRunExploratoryTest(args)
            elif toolName == "run_single_page_test":
                result = await handleRunSinglePageTest(args)
            elif toolName == "get_test_status":
                result = await handleGetTestStatus(args)
            elif toolName == "stop_test":
                result = await handleStopTest(args)
            elif toolName == "list_sessions":
                result = await handleListSessions(args)
            else:
                raise MCPError(types.METHOD_NOT_FOUND, f"未知工具：{toolName}")
            return types.CallToolResult(content=[types.TextContent(**item) for item in result["content"]])
        except Exception as error:
            logger.error(f"工具 {toolName} 执行失败：{error}")
            raise MCPError(types.INTERNAL_ERROR, str(error)) from error

    async def _on_list_resources(self, context, params):
        return types.ListResourcesResult(resources=[
            types.Resource(uri="test-report://latest", name="最新测试报告",
                mimeType="text/markdown", description="最近生成的测试报告"),
            types.Resource(uri="test-report://{sessionId}", name="按会话查看测试报告",
                mimeType="text/markdown", description="指定会话的 Markdown 测试报告")])

    async def _on_read_resource(self, context, params):
        uri = str(params.uri)
        if uri.startswith("test-report://"):
            result = await handleTestReportResource(uri)
            return types.ReadResourceResult(contents=[types.TextResourceContents(**item)
                                                      for item in result["contents"]])
        raise MCPError(types.INVALID_REQUEST, f"未知资源地址：{uri}")

    async def start(self):
        async with stdio_server() as (read_stream, write_stream):
            logger.log("MCP 服务已通过标准输入输出连接")
            await self.server.run(read_stream, write_stream,
                                  self.server.create_initialization_options())

    async def stop(self):
        logger.log("MCP 服务已停止")
