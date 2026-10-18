"""TDD：P0 T5 恢复路径修复——resume 时 seed 单元必须带完整产物上下文。

缺陷：engine.resume_task 传 seed_done=set() → orchestrator 建空壳 UnitResult
（无 artifacts）→ 下游 _dep_context 读不到产物 → plan/result 为空 →
prompt 与首次不同 → 回复缓存失效（cache_bench recovery 100% → 33%）。
"""
import pathlib
import tempfile

from wuxing.config import EngineConfig
from wuxing.llm.tool_results import ToolCallResult
from wuxing.orchestrator import Orchestrator
from wuxing.protocols import Artifact, UnitResult
from wuxing.registry import DomainRegistry
from wuxing.tools.loader import load_tools
from wuxing.workspace import Workspace


def test_seed_units_with_artifacts_flow_to_dependents():
    """seed_done 传完整 UnitResult（带 artifacts）时，下游 plan = 产物内容。"""
    cfg = EngineConfig(max_loop_rounds=6, max_unit_budget=4)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    # 模拟首次运行已产出的计划产物（resume 场景的真实状态）
    ws.write_artifact(Artifact(path="F-plan0-plan.md", kind="plan",
                               producer_unit="F-plan0"), "计划内容：步骤1 步骤2 步骤3")
    seed = {
        "F-plan0": UnitResult(unit_id="F-plan0", domain_id="plan", status="ok",
                              artifacts=[Artifact(path="F-plan0-plan.md",
                                                  kind="plan",
                                                  producer_unit="F-plan0")]),
    }

    class ProbeLlm:
        def __init__(self):
            self.seen = []

        def name(self):
            return "probe"

        def chat(self, messages, tools=None):
            self.seen.append(messages)
            return ToolCallResult(text="执行完成：已完成。产物：result.md", tool_calls=[
                {"name": "write_artifact",
                 "arguments": {"path": "out.md", "kind": "result",
                               "content": "执行成果：已完成"}}])

    llm = ProbeLlm()
    orch = Orchestrator(cfg, DomainRegistry(cfg), ws, llm, load_tools(ws))
    frags = [{"fragment_id": "F-exec1", "domain": "execute", "deps": ["F-plan0"],
              "text": "实现", "_forced": True}]
    orch.run(frags, "写请假邮件", seed_done=seed)
    exec_msgs = llm.seen[0]
    exec_text = " ".join(str(m.get("content", "")) for m in exec_msgs)
    assert "计划内容：步骤1" in exec_text, \
        f"resume 下游必须看到产物内容（恢复链断点）：{exec_text[:200]!r}"
