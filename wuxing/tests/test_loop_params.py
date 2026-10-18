"""TDD：P0 T2 参数接线（S3 碎片文本/ S4 产物内容入 prompt）。

旧缺陷：goal=整个任务（碎片文本只进智脑键）；plan=UnitResult repr 垃圾；
result 永为空（verify 不知道验什么）。本文件断言 prompt 实际内容。
"""
import pathlib
import tempfile

from wuxing.config import EngineConfig
from wuxing.llm.tool_results import ToolCallResult
from wuxing.orchestrator import Orchestrator
from wuxing.registry import DomainRegistry
from wuxing.tools.loader import load_tools
from wuxing.workspace import Workspace


class ConvergentRecordingLlm:
    """按域标记收敛的假 LLM：plan 写产物、execute/verify 输出带 marker；记录 messages。"""

    def __init__(self):
        self.calls = 0
        self.seen = []

    def name(self):
        return "convergent"

    def chat(self, messages, tools=None):
        self.calls += 1
        self.seen.append([dict(m) for m in messages])
        text = " ".join(m["content"] for m in messages
                        if isinstance(m.get("content"), str))
        if "域：plan" in text:
            return ToolCallResult(text="方案：完整执行计划", tool_calls=[
                {"name": "write_artifact",
                 "arguments": {"path": "artifacts/plan.md", "kind": "plan",
                               "content": "计划内容：先写请假邮件主体，再检查格式"}}])
        if "域：execute" in text:
            return ToolCallResult(
                text="执行成果：已完成。产物：result.md",
                tool_calls=[{"name": "write_artifact", "arguments": {
                    "path": "artifacts/result.md", "kind": "result",
                    "content": "执行成果：请假邮件应用已实现"}}])
        if "域：verify" in text:
            return ToolCallResult(
                text="评审结论：通过。产物满足验收标准",
                tool_calls=[{"name": "read_dependency",
                             "arguments": {"path": "artifacts/result.md"}}])
        return "（兜底）完成"


def _run_three_fragments():
    """plan → execute → verify 三碎片（依赖链）跑一遍，返回 (orchestrator, llm, ws)。"""
    cfg = EngineConfig(max_loop_rounds=6, max_unit_budget=4)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    llm = ConvergentRecordingLlm()
    orch = Orchestrator(cfg, DomainRegistry(cfg), ws, llm, load_tools(ws))
    fragments = [
        {"fragment_id": "F-plan0", "domain": "plan", "deps": [],
         "text": "制定请假流程", "_forced": True},
        {"fragment_id": "F-exec1", "domain": "execute", "deps": ["F-plan0"],
         "text": "实现请假邮件应用", "_forced": True},
        {"fragment_id": "F-ver2", "domain": "verify", "deps": ["F-exec1"],
         "text": "验证请假邮件", "_forced": True},
    ]
    results = orch.run(fragments, "写一个请假邮件应用")
    return orch, llm, ws, results


def test_fragment_text_is_goal():
    """S3：execute 碎片的 goal = 碎片文本（自身小的那部分），不是全任务。"""
    _, llm, _, results = _run_three_fragments()
    assert all(r.status == "ok" for r in results), [r.error for r in results]
    # 找到 execute 碎片的调用（第 2 次调用 = 第一碎片第一轮 plan；按域筛选）
    exec_seen = next(m for m in llm.seen
                     if any("域：execute" in str(x.get("content", "")) for x in m))
    exec_text = " ".join(str(x.get("content", "")) for x in exec_seen)
    assert "实现请假邮件应用" in exec_text, "碎片文本（goal）必须进入 prompt"
    assert "UnitResult(" not in exec_text, "plan 不得注入对象 repr 垃圾"


def test_plan_param_is_artifact_content():
    """S4：execute 的 plan = 依赖产物【内容】（前一 unit 收口写入的产物），
    不是 UnitResult 对象 repr。"""
    _, llm, _, results = _run_three_fragments()
    assert all(r.status == "ok" for r in results)
    exec_seen = next(m for m in llm.seen
                     if any("域：execute" in str(x.get("content", "")) for x in m))
    exec_text = " ".join(str(x.get("content", "")) for x in exec_seen)
    assert "计划内容" in exec_text, \
        "plan 参数必须是【真实交付物】内容（写工具写出的文件而非契约叙述）"
    assert "UnitResult(" not in exec_text


def test_verify_receives_plan_dependency_content():
    """冒烟 F3：verify 域直接依赖 plan 产物时，result 也必须含内容（被验对象）。

    真 LLM 冒烟实证：verify deps=plan → 旧逻辑把 plan 产物归入 plan 字段 →
    result 空 → LLM 不知道验收什么（臆想检查后输出"未通过"）。
    """
    cfg = EngineConfig(max_loop_rounds=6, max_unit_budget=4)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    llm = ConvergentRecordingLlm()
    orch = Orchestrator(cfg, DomainRegistry(cfg), ws, llm, load_tools(ws))
    fragments = [
        {"fragment_id": "F-plan0", "domain": "plan", "deps": [],
         "text": "制定方案", "_forced": True},
        {"fragment_id": "F-ver1", "domain": "verify", "deps": ["F-plan0"],
         "text": "验证方案内容", "_forced": True},
    ]
    results = orch.run(fragments, "写请假邮件")
    assert all(r.status == "ok" for r in results), [r.error for r in results]
    ver_seen = next(m for m in llm.seen
                    if any("域：verify" in str(x.get("content", "")) for x in m))
    ver_text = " ".join(str(x.get("content", "")) for x in ver_seen)
    assert "计划内容" in ver_text, \
        f"verify 的 result 必须含真实交付物内容：{ver_text[:200]!r}"


def test_verify_receives_artifact_paths():
    """冒烟根因2：verify 必须知道被验产物【路径】（此前只有内容——LLM 盲猜
    路径 → read not found → 永远在勘察 → budget 耗尽）。"""
    cfg = EngineConfig(max_loop_rounds=6, max_unit_budget=4)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    llm = ConvergentRecordingLlm()
    orch = Orchestrator(cfg, DomainRegistry(cfg), ws, llm, load_tools(ws))
    fragments = [
        {"fragment_id": "F-plan0", "domain": "plan", "deps": [],
         "text": "制定方案", "_forced": True},
        {"fragment_id": "F-exec1", "domain": "execute", "deps": ["F-plan0"],
         "text": "实现", "_forced": True},
        {"fragment_id": "F-ver2", "domain": "verify", "deps": ["F-exec1"],
         "text": "验证", "_forced": True},
    ]
    results = orch.run(fragments, "写请假邮件")
    assert all(r.status == "ok" for r in results), [r.error for r in results]
    ver_seen = next(m for m in llm.seen
                    if any("域：verify" in str(x.get("content", "")) for x in m))
    ver_text = " ".join(str(x.get("content", "")) for x in ver_seen)
    assert "artifacts/result.md" in ver_text, \
        f"verify 必须收到被验产物路径（真实交付物）：{ver_text[:260]!r}"
    assert "待验产物路径" in ver_text, f"路径段缺失：{ver_text[:260]!r}"
    assert "结论：通过" in ver_text or "给出明确结论" in ver_text, \
        "verify 契约应明确要求给出结论（勘察型文本导致不收敛——冒烟根因）"


def test_verify_receives_result_content():
    """S4：verify 的 result = 被验产物内容（不再是空串——否则验收无的放矢）。"""
    _, llm, _, results = _run_three_fragments()
    assert all(r.status == "ok" for r in results)
    ver_seen = next(m for m in llm.seen
                    if any("域：verify" in str(x.get("content", "")) for x in m))
    ver_text = " ".join(str(x.get("content", "")) for x in ver_seen)
    assert "执行成果" in ver_text, "result 参数必须是 execute 产物内容（含『执行成果：已完成』）"
    assert "UnitResult(" not in ver_text
