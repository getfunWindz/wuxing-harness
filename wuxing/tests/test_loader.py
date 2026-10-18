import pathlib
import tempfile

from wuxing.tools.loader import ToolLoaderConfig, load_tools
from wuxing.workspace import Workspace


def test_loader_builtin_and_fs():
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    reg = load_tools(ws, ToolLoaderConfig(mcp_servers=[]))
    names = {t.name() for t in reg.list()}
    assert {"write_artifact", "read_dependency", "read_file", "write_file", "bash"} <= names
    assert isinstance(reg, __import__("wuxing.tools.base", fromlist=["ToolRegistry"]).ToolRegistry)

def test_loader_with_mcp_config():
    import sys
    import textwrap

    from wuxing.tools.mcp_bridge import McpServerConfig
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    tmp = pathlib.Path(tempfile.mkdtemp())
    srv = tmp / "srv.py"
    srv.write_text(textwrap.dedent('''
from mcp.server.fastmcp import FastMCP
m = FastMCP("t")
@m.tool()
def ping() -> str:
    return "pong"
if __name__ == "__main__":
    m.run()
'''), encoding="utf-8")
    cfg = ToolLoaderConfig(mcp_servers=[McpServerConfig(name="t", command=sys.executable, args=["-u", str(srv)])])
    reg = load_tools(ws, cfg)
    names = {t.name() for t in reg.list()}
    assert "mcp__t__ping" in names
