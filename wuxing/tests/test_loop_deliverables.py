"""TDD：S-C 验收语义闭环（真冒烟根因——execute 收口叙述与真实交付物割裂）。

冒烟实证：execute ok 时契约产物 = 过程叙述（"我已经读取了方案文件…"）→
verify 读叙述无法判定；真实交付物（fibonacci.py）在工件区但 verify 不知道。
修复：真实交付物追踪（write 工具成功 → deliverables）+ _dep_context 优先注入。
"""
import pathlib
import tempfile

from wuxing.config import EngineConfig
from wuxing.llm.tool_results import ToolCallResult
from wuxing.orchestrator import Orchestrator
from wuxing.registry import DomainRegistry
from wuxing.runner import Runner
from wuxing.tools.loader import load_tools
from wuxing.workspace import Workspace


class DeliverableLlm:
    """真交付物型 LLM：写真实代码文件后摘要收口（模拟冒烟中的正确行为）。"""

    def __init__(self):
        self.calls = 0
        self.seen = []

    def name(self):
        return "deliv"

    def chat(self, messages, tools=None):
        self.calls += 1
        self.seen.append([dict(m) for m in messages])
        text = " ".join(m["content"] for m in messages
                        if isinstance(m.get("content"), str))
        if "域：execute" in text:
            joined = " ".join(m["content"] for m in messages
                              if isinstance(m.get("content"), str))
            if "我已经读取" in joined or "written" in joined:
                return "执行完成：已实现 fibonacci.py（含递归实现）"
            return ToolCallResult(text="我已经读取了方案文件，现在按照方案执行步骤", tool_calls=[
                {"name": "write_artifact",
                 "arguments": {"path": "fibonacci.py", "kind": "code",
                               "content": "def fibonacci(n):\n    return 1 if n<2 else fibonacci(n-1)+fibonacci(n-2)"}}])
        if "域：verify" in text:
            return ToolCallResult(text="评审结论：通过。产物满足验收标准", tool_calls=[
                {"name": "read_file", "arguments": {"path": "fibonacci.py"}}])
        return ToolCallResult(text="方案：完整执行计划", tool_calls=[
            {"name": "write_artifact",
             "arguments": {"path": "plan.md", "kind": "plan", "content": "计划内容"}}])


def test_runner_collects_real_deliverables():
    """写工具成功 → UnitResult.deliverables 记录真实交付物路径。"""
    cfg = EngineConfig(max_loop_rounds=6, max_unit_budget=4)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    llm = DeliverableLlm()
    r = Runner(cfg, DomainRegistry(cfg), ws, llm, load_tools(ws))
    res = r.run_unit("U-1", "execute", {"goal": "实现斐波那契", "task": "全任务"})
    assert res.status == "ok", res.error
    assert "fibonacci.py" in res.deliverables, \
        f"真实交付物必须被追踪：{res.deliverables}"


def test_dep_context_prefers_real_deliverables():
    """verify 的 result/paths 优先注入真实交付物内容（非契约叙述）。"""
    cfg = EngineConfig(max_loop_rounds=6, max_unit_budget=4)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    llm = DeliverableLlm()
    orch = Orchestrator(cfg, DomainRegistry(cfg), ws, llm, load_tools(ws))
    fragments = [
        {"fragment_id": "F-plan0", "domain": "plan", "deps": [],
         "text": "制定方案", "_forced": True},
        {"fragment_id": "F-exec1", "domain": "execute", "deps": ["F-plan0"],
         "text": "实现斐波那契", "_forced": True},
        {"fragment_id": "F-ver2", "domain": "verify", "deps": ["F-exec1"],
         "text": "验证斐波那契", "_forced": True},
    ]
    results = orch.run(fragments, "写斐波那契")
    assert all(r.status == "ok" for r in results), [r.error for r in results]
    ver_seen = next(m for m in llm.seen
                    if any("域：verify" in str(x.get("content", "")) for x in m))
    ver_text = " ".join(str(x.get("content", "")) for x in ver_seen)
    # 关键断言：verify 收到真实代码内容（而非"我已经读取了方案文件"叙述）
    assert "def fibonacci" in ver_text, \
        f"verify 必须收到真实交付物内容（叙述型不得算）：{ver_text[:300]!r}"
    assert "fibonacci.py" in ver_text, f"verify 必须知道真实交付物路径：{ver_text[:300]!r}"
