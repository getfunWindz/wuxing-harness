import asyncio

from wuxing.tools.mcp_bridge import McpServerConfig, load_mcp_tools

# 测试用 MCP server：echo 工具
_MCP_SRV = '''
from mcp.server.fastmcp import FastMCP
m = FastMCP("test")
@m.tool()
def echo(text: str) -> str:
    """返回输入文本"""
    return "echo:" + text
if __name__ == "__main__":
    m.run()
'''

def _mk_configs():
    import pathlib
    import sys
    import tempfile
    import textwrap
    tmp = pathlib.Path(tempfile.mkdtemp())
    srv = tmp / "srv.py"
    srv.write_text(textwrap.dedent(_MCP_SRV), encoding="utf-8")
    return [McpServerConfig(name="test", command=sys.executable, args=["-u", str(srv)])]

def test_load_mcp_tools_roundtrip():
    tools = asyncio.run(load_mcp_tools(_mk_configs()))
    assert any(t.name() == "mcp__test__echo" for t in tools)
    echo = next(t for t in tools if t.name() == "mcp__test__echo")
    out = echo.execute(text="hi")
    assert out.status == "ok"
    assert out.content == "echo:hi"

def test_mcp_tool_has_schema_and_description():
    tools = asyncio.run(load_mcp_tools(_mk_configs()))
    echo = next(t for t in tools if t.name() == "mcp__test__echo")
    assert "text" in str(echo.input_schema())
    assert echo.description() != ""


def test_mcp_tool_timeout_returns_error():
    """阶段 3b：MCP 工具超时（挂起 server 不挂引擎）——审查报告 #19 修复。"""
    import asyncio

    from wuxing.tools.mcp_bridge import McpServerConfig, McpToolAdapter

    class HangAdapter(McpToolAdapter):
        async def _async_call(self, kwargs):
            await asyncio.sleep(60)  # 模拟挂起 server

    a = HangAdapter("hang", "slow", "desc", {}, McpServerConfig(name="x", command="y"),
                    timeout=2)
    out = a.execute()
    assert out.status == "error"
    assert "timeout" in (out.error or "").lower()


class _CountingServer:
    """计数 stdio server：记录 initialize 次数——验证连接复用（常驻连接）。"""

    def __init__(self):
        self.init_count = 0

    def run(self):
        pass


def test_mcp_pool_reuses_connection():
    """E1：MCP 连接池——同一 server 多次调用只 initialize 一次（持久连接复用）。"""
    import asyncio
    import pathlib
    import sys

    from wuxing.tools.mcp_bridge import McpConnectionPool, McpServerConfig
    # 用 echo server 文件路径（真实 stdio server）
    _SERVER = str(pathlib.Path(__file__).with_name("mcp_echo_server.py"))
    cfg = McpServerConfig(name="echo", command=sys.executable,
                          args=[_SERVER],
                          permissions={"read": True, "execute": True})
    pool = McpConnectionPool()
    try:
        results = []

        async def two_calls():
            async def call():
                out = await pool.call_tool(cfg, "echo", {"text": "hi"})
                return out
            r1 = await call()
            r2 = await call()
            results.append((r1, r2))

        asyncio.run(two_calls())
        assert "echo: hi" in results[0][0]
        assert "echo: hi" in results[0][1]
        assert pool.stats[cfg.name]["connections"] == 1, \
            f"连接必须复用（实际 {pool.stats[cfg.name]['connections']}）"
        assert pool.stats[cfg.name]["calls"] == 2
    finally:
        pool.close()


def test_mcp_pool_reuses_connection_via_adapter():
    """E1 生产路径回归：McpToolAdapter.execute（同步入口——每次调用内部起
    asyncio.run）也必须复用同一连接——修复跨事件循环复用失效。

    缺陷证据（2026-09-11 审查）：修复前 3 次 execute → 3 次建连（每次重连）
    + anyio 跨 loop 清理异常；原测试在单 loop 内直调 pool.call_tool，
    绕过了生产路径，导致假绿。
    """
    import pathlib
    import sys

    from wuxing.tools.mcp_bridge import (
        McpConnectionPool,
        McpServerConfig,
        McpToolAdapter,
    )
    _SERVER = str(pathlib.Path(__file__).with_name("mcp_echo_server.py"))
    cfg = McpServerConfig(name="echo-adapter", command=sys.executable,
                          args=[_SERVER], permissions={"read": True})
    pool = McpConnectionPool()
    adapter = McpToolAdapter(
        "echo-adapter", "echo", "回声",
        {"type": "object", "properties": {"text": {"type": "string"}}},
        cfg, pool=pool)
    try:
        r1 = adapter.execute(text="one")
        r2 = adapter.execute(text="two")
        r3 = adapter.execute(text="three")
        assert r1.status == "ok" and "echo: one" in (r1.content or "")
        assert r2.status == "ok" and "echo: two" in (r2.content or "")
        assert r3.status == "ok" and "echo: three" in (r3.content or "")
        assert pool.stats["echo-adapter"]["connections"] == 1, \
            ("同一 adapter 多次调用必须复用连接"
             f"（实际 {pool.stats['echo-adapter']['connections']} 次建连）")
    finally:
        pool.close()
