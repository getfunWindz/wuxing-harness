"""TDD · M1-5/v4-flash 实测发现：写物证=完成充分证据（thinking 模型工具轮无文本）。

契约原判：文本含 marker AND 物证——v4-flash 五轮纯工具调用（写产物、无文本）
→ 永不通过 → failed。机制裁决：事实产出 > 自报声明（verify 域负责质量把关）。
"""
import pathlib
import tempfile

from wuxing.config import EngineConfig
from wuxing.registry import DomainRegistry
from wuxing.runner import Runner
from wuxing.tools.builtin import BUILTIN_TOOLS
from wuxing.workspace import Workspace


class _ToolOnlyLlm:
    """多轮：每轮只调写工具（无文本输出——thinking 模型工具轮模式）后停止。"""

    def __init__(self):
        self.calls = 0

    def name(self):
        return "tool-only"

    def chat(self, messages, tools=None):
        from wuxing.llm.tool_results import ToolCallResult
        self.calls += 1
        if self.calls <= 5:
            return ToolCallResult(text="", tool_calls=[
                {"name": "write_artifact",
                 "arguments": {"path": "plan.md", "kind": "plan",
                               "content": "完整方案文本" * 10}}])
        return "方案：最终方案"  # 超时的 fallback（不应到达——预算内应已收敛）


def test_write_evidence_suffices_for_execute_domain():
    """execute 域（require_write）：写物证成功 → 单元完成（无需文本 marker——物证>自报）。"""
    cfg = EngineConfig(max_loop_rounds=6, max_unit_budget=5)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    llm = _ToolOnlyLlm()
    r = Runner(cfg, DomainRegistry(cfg), ws, llm, BUILTIN_TOOLS(ws))
    res = r.run_unit("U-1", "execute", {"goal": "g"})
    assert res.status == "ok", f"写物证完成必须判通过（产物=事实）：{res.error}"
    assert (ws.root / "plan.md").exists(), "产物必须真实落盘"


def test_no_evidence_text_only_rejected():
    """对照：无写物证纯文本（无 marker）→ 不通过（空洞声明≠完成）。"""
    class _TextOnly:
        def name(self):
            return "text-only"

        def chat(self, messages, tools=None):
            return "我完成任务了但是没有产物文件"

    cfg = EngineConfig(max_loop_rounds=3, max_unit_budget=2)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    r = Runner(cfg, DomainRegistry(cfg), ws, _TextOnly(), BUILTIN_TOOLS(ws))
    res = r.run_unit("U-1", "execute", {"goal": "g"})
    assert res.status == "failed", "无产物物证不得判完成（空洞声明）"
