"""最简单的 MCP Server 示例，使用官方 Python SDK。

启动方式：
    uv run python -m learning_py.mcp_server.server

该服务通过 stdio 传输协议暴露一个 tool：`add`，用于计算两数之和。
"""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("DemoServer")


@mcp.tool()
def add(a: float, b: float) -> float:
    """计算两个数的和。"""
    return a + b


@mcp.tool()
def greet(name: str) -> str:
    """向指定的人打招呼。"""
    return f"Hello, {name}! 👋"


if __name__ == "__main__":
    mcp.run()
