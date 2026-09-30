"""mcp：启动 MCP stdio server（等价 python -m src.mcp.index，信号处理在其内）。"""
import asyncio

import typer


def mcp_command():
    from src.mcp.index import main as mcp_main  # 延迟导入：--version/--help 不拖起 MCP 依赖

    try:
        asyncio.run(mcp_main())
    except KeyboardInterrupt:
        raise typer.Exit(0)
