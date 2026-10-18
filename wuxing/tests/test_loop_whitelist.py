"""TDD：P0 T4 白名单分层（S6——verify/execute 开放 read_file 真物验）。"""
import pathlib
import tempfile

from wuxing.config import EngineConfig
from wuxing.llm.tool_results import ToolCallResult
from wuxing.protocols import Artifact
from wuxing.registry import DomainRegistry
from wuxing.runner import Runner
from wuxing.tools.loader import load_tools
from wuxing.workspace import Workspace


def test_verify_can_use_read_file():
    """S6：verify 域白名单必须含 read_file——验收需读真实文件内容（物证）。"""
    class ReadFileLlm:
        def name(self):
            return "readfile"

        def chat(self, messages, tools=None):
            return ToolCallResult(text="评审结论：通过。已实际读取产物内容", tool_calls=[
                {"name": "read_file", "arguments": {"path": "result.md"}}])

    cfg = EngineConfig(max_loop_rounds=6, max_unit_budget=3)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    ws.write_artifact(Artifact(path="result.md", kind="result",
                               producer_unit="F-exec"), "登录页已实现: <h1>login</h1>")
    r = Runner(cfg, DomainRegistry(cfg), ws, ReadFileLlm(), load_tools(ws))
    res = r.run_unit("U-1", "verify", {"result": "result.md 内容"})
    assert res.status == "ok", f"read_file 应被白名单放行并构成读物证：{res.error}"
    assert "read_file" not in r._blocked_tools, "read_file 不得被拦截"


def test_execute_can_read_dependencies_via_read_file():
    """S6：execute 域也应能 read_file（读依赖/上游文件再执行）。"""
    class ExecReadFileLlm:
        def __init__(self):
            self.calls = 0

        def name(self):
            return "execread"

        def chat(self, messages, tools=None):
            self.calls += 1
            if self.calls == 1:
                return ToolCallResult(text="我先读取依赖文件", tool_calls=[
                    {"name": "read_file", "arguments": {"path": "spec.md"}},
                    {"name": "write_artifact",
                     "arguments": {"path": "out.md", "kind": "result",
                                   "content": "实现完成"}}])
            return "执行完成：产物 out.md 已产出"

    cfg = EngineConfig(max_loop_rounds=6, max_unit_budget=4)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    ws.write_artifact(Artifact(path="spec.md", kind="plan",
                               producer_unit="F-plan0"), "需求：登录页含输入框与按钮")
    r = Runner(cfg, DomainRegistry(cfg), ws, ExecReadFileLlm(), load_tools(ws))
    res = r.run_unit("U-1", "execute", {"goal": "实现登录页"})
    assert res.status == "ok", f"execute 应可 read_file：{res.error}"
    assert "read_file" not in r._blocked_tools
