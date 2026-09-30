"""MCP stdio server exposing WebAudit tools and resources."""

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.shared.exceptions import MCPError

from src.mcp.resources.reports import handle_test_report_resource
from src.mcp.tools.definitions import TOOL_DEFINITIONS
from src.mcp.tools.exploratory import handle_run_exploratory_test
from src.mcp.tools.sessions import handle_list_sessions
from src.mcp.tools.single_page import handle_run_single_page_test
from src.mcp.tools.status import handle_get_test_status, handle_stop_test
from src.utils.logger import create_logger

logger = create_logger("mcp-server")
active_tests = {}


class TestingAgentMCPServer:
    def __init__(self):
        self.server = Server("qa-agent-testing", version="1.0.0",
            on_list_tools=self._on_list_tools, on_call_tool=self._on_call_tool,
            on_list_resources=self._on_list_resources,
            on_read_resource=self._on_read_resource)
        self.setup_handlers()

    def setup_handlers(self):
        return None

    async def _on_list_tools(self, context, params):
        return types.ListToolsResult(tools=[types.Tool(**definition) for definition in TOOL_DEFINITIONS])

    async def _on_call_tool(self, context, params):
        tool_name = params.name
        args = params.arguments or {}
        logger.info(f"调用工具：{tool_name}，参数：{args}")
        try:
            if tool_name == "run_exploratory_test":
                result = await handle_run_exploratory_test(args)
            elif tool_name == "run_single_page_test":
                result = await handle_run_single_page_test(args)
            elif tool_name == "get_test_status":
                result = await handle_get_test_status(args)
            elif tool_name == "stop_test":
                result = await handle_stop_test(args)
            elif tool_name == "list_sessions":
                result = await handle_list_sessions(args)
            else:
                raise MCPError(types.METHOD_NOT_FOUND, f"未知工具：{tool_name}")
            return types.CallToolResult(content=[types.TextContent(**item) for item in result["content"]])
        except Exception as error:
            logger.error(f"工具 {tool_name} 执行失败：{error}")
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
            result = await handle_test_report_resource(uri)
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
