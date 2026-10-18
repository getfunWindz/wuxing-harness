import pathlib
import tempfile

from wuxing.tools.base import ToolRegistry
from wuxing.tools.builtin import BUILTIN_TOOLS
from wuxing.workspace import Workspace


def _reg():
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    return ToolRegistry(BUILTIN_TOOLS(ws))

def test_builtin_tools_present():
    reg = _reg()
    assert reg.get("write_artifact") is not None
    assert reg.get("read_dependency") is not None

def test_tool_schema_wellformed():
    reg = _reg()
    for t in reg.list():
        assert t.input_schema().get("type") == "object"

def test_whitelist_filter():
    reg = _reg()
    tools = reg.filter(("write_artifact",))
    assert [t.name() for t in tools] == ["write_artifact"]

def test_write_artifact_tool_blocks_escape():
    # 审查发现：write_artifact 是各域白名单工具——路径逃逸必须被拦
    # （嵌套 work 子目录：逃逸落点在临时目录内自包含，无跨测试残留污染）
    with tempfile.TemporaryDirectory() as tmp:
        ws = Workspace(pathlib.Path(tmp) / "work")
        reg = ToolRegistry(BUILTIN_TOOLS(ws))
        out = reg.execute("write_artifact", path="../evil.txt", content="PWNED")
        assert out.status == "blocked"  # 阶段 3：结构化态
        assert "escape" in out.error
        assert not (pathlib.Path(tmp) / "evil.txt").exists()


def test_tool_execute_returns_structured_result():
    """阶段 3：Tool execute 返回结构化 ToolResult（status ok|blocked|error）。
    此前全字符串混拼（[guard] blocked/error:/正常输出不可区分）——DSH Consumer 协议参考。"""
    from wuxing.protocols import ToolResult
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    reg = ToolRegistry(BUILTIN_TOOLS(ws))
    r = reg.execute("write_artifact", path="a.txt", content="hi")
    assert isinstance(r, ToolResult)
    assert r.status == "ok"
    assert "written" in r.content
    # 未知工具 → error 态（结构化而非混拼文本）
    r2 = reg.execute("nope_tool")
    assert r2.status == "error"
    # guard 拦截 → blocked 态
    reg.set_guard(lambda name, kwargs: False)
    r3 = reg.execute("write_artifact", path="b.txt", content="x")
    assert r3.status == "blocked"
