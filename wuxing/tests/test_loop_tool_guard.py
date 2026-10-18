"""TDD：冒烟根因3——工具执行的异常防护（挂起不挂引擎）。

冒烟实证：verify LLM read_file 猜路径读到【目录】→ p.read_text 抛
PermissionError → 冲破 run_unit → 任务 exception（真 LLM 冒烟捕获）。
知识库「工具工程实践」：工具护栏——超时/异常不挂引擎。
"""
import pathlib
import tempfile

from wuxing.tools.base import ToolRegistry
from wuxing.tools.fs_tools import ReadFileTool
from wuxing.workspace import Workspace


def test_read_file_dir_returns_error_not_exception():
    """读目录/无权限：返回结构化 error（ToolResult），不得抛异常。"""
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    sub = ws.root / "subdir"
    sub.mkdir()  # 目录存在（LLM 猜路径的场景）
    t = ReadFileTool(ws)
    res = t.execute(path="subdir")
    assert res.status == "error", f"目录读取应结构化失败：{res.status}"
    assert "directory" in res.error.lower(), f"错误文案应说明目录：{res.error}"


class ExplodingTool:
    def name(self):
        return "explode"

    def description(self):
        return "execution raises"

    def input_schema(self):
        return {"type": "object"}

    def permission(self):
        return {"read": False, "write": False, "execute": True,
                "network": False, "destructive": False}

    def execute(self, **kwargs):
        raise PermissionError("boom: 模拟工具内部异常")


def test_registry_execute_catches_tool_exceptions():
    """ToolRegistry.execute：工具 execute 抛异常 → 转 ToolResult(error)（机制兜底）。"""
    reg = ToolRegistry([ExplodingTool()])
    res = reg.execute("explode")
    assert res.status == "error"
    assert "boom" in res.error or "PermissionError" in res.error
