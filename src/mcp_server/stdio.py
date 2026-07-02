"""MCP stdio transport entry point.

Run with: python -m src.mcp_server.stdio
"""

import asyncio

from mcp.server.stdio import stdio_server

from src.mcp_server.server import app


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
