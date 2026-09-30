"""MCP stdio server entry point."""

import asyncio
import signal
import sys

from src.mcp.server import TestingAgentMCPServer


async def main():
    mcpServer = TestingAgentMCPServer()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(mcpServer.stop()))
    await mcpServer.start()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as error:
        print("MCP 服务发生严重错误：", error, file=sys.stderr)
        sys.exit(1)
