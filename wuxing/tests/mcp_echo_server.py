"""mini MCP server fixture（L2-1 端到端：stdio —— FastMCP 单工具）。"""
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("echo-server")


@mcp.tool()
def echo(text: str) -> str:
    """回声工具：返回输入文本（端到端验证工具调用链）。"""
    return f"echo: {text}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
