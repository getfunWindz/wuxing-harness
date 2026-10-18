"""TDD：P3 T2 工具权限声明层（最小权限——DSH 教训：默认拒绝、按需授予）。"""
import pathlib
import tempfile

from wuxing.tools.base import ToolRegistry
from wuxing.tools.bash_tool import BashTool
from wuxing.tools.builtin import WriteArtifactTool
from wuxing.tools.fs_tools import WriteFileTool
from wuxing.workspace import Workspace


class UndeclaredTool:
    """未声明权限的工具（默认全 False——最小权限）。"""

    def name(self):
        return "undeclared"

    def description(self):
        return "tool without permission declaration"

    def input_schema(self):
        return {"type": "object"}

    def execute(self, **kwargs):
        return "executed"


def test_undeclared_tool_blocked_by_registry():
    """未声明权限 → Registry 拦截（最小权限：默认拒绝）。"""
    reg = ToolRegistry([UndeclaredTool()])
    res = reg.execute("undeclared")
    assert res.status == "blocked", f"未声明权限工具必须被拦截：{res.status}"
    assert "permission" in res.error.lower(), res.error


def test_declared_tools_still_work():
    """声明权限的工具正常执行（write_artifact=write / write_file=write）。"""
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    reg = ToolRegistry([WriteArtifactTool(ws), WriteFileTool(ws)])
    res = reg.execute("write_artifact", path="a.md", content="x")
    assert res.status == "ok", f"声明 write 的工具应放行：{res.error}"
    res2 = reg.execute("write_file", path="b.md", content="y")
    assert res2.status == "ok"


def test_bash_declares_execute_network_destructive():
    """bash 声明 execute/network/destructive（能力面真实——由守卫/白名单约束）。"""
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    p = BashTool(ws).permission()
    assert p["execute"] is True
    assert p["network"] is True
    assert p["destructive"] is True


def test_permission_declaration_complete():
    """所有内置工具必须声明权限（不允许静默缺省导致不可用或被绕过）。"""
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    from wuxing.tools.loader import load_tools
    registry = load_tools(ws)
    for name, tool in registry._tools.items():
        perm = tool.permission()
        assert any(perm.values()), f"{name} 必须声明至少一项权限（声明制）"
