"""TDD · L3-4：记忆评测——brain_pick 来源标记 → 记忆引导成功率指标（智脑收益实证铺路）。

知识库 7 步「⑦评测记忆质量」：记忆命中是否导向成功——可量化前「智脑收益
未证明」无从更新。本层：选择来源落 trace/metrics（机制层可归因）；真实 A/B
收益对比待 LLM 解冻（离线 mock 验证管道）。
"""
import pathlib
import tempfile

from wuxing.evaluate import compute_memory_metrics
from wuxing.llm.brain import BrainMemory
from wuxing.llm.router import ModelRouter
from wuxing.protocols import UnitResult


def _mk_brain_with_case(key="读文件并分析数据"):
    bm = BrainMemory(pathlib.Path(tempfile.mkdtemp()) / "b.json")
    bm.cases.append({"key": key, "domain": "execute", "model": "m",
                     "spec": "deepseek:deepseek-chat", "success": True,
                     "attempts": 1, "tier": "normal", "last_at": 1e12})
    return bm


def test_brain_pick_marks_provider():
    """L3-4：brain 命中 → provider._picked_by_brain=True（选择来源可归因）。"""
    bm = _mk_brain_with_case()
    router = ModelRouter({"execute": "deepseek:deepseek-chat"}, brain=bm)
    p = router.for_domain("execute", "读文件并分析数据 生成报表")
    assert getattr(p, "_picked_by_brain", False) is True, "brain 选择必须标记"


def test_fallback_no_mark():
    """L3-4：无记忆证据 → 回退候选，无 brain 标记。"""
    router = ModelRouter({"execute": "deepseek:deepseek-chat"})
    p = router.for_domain("execute", "无关任务文本")
    assert getattr(p, "_picked_by_brain", False) is False


def test_unit_metrics_include_memory():
    """L3-4：runner 单元 metrics 含 memory 段（选择来源随单元入 trace/指标）。"""
    from wuxing.config import EngineConfig as EC
    from wuxing.registry import DomainRegistry
    from wuxing.runner import Runner
    from wuxing.tools.builtin import BUILTIN_TOOLS
    from wuxing.workspace import Workspace

    class FakeLlm:
        def __init__(self):
            self.call_count = 0
            self.usage_history = []
            self._picked_by_brain = True
            self._mem_spec = "mock:brain"

        def name(self):
            return "fake"

        def chat(self, messages, tools=None):
            self.call_count += 1
            return "从用户视角定义验收标准：可用"

    cfg = EC(max_unit_budget=3)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    reg = DomainRegistry(cfg)
    reg.activate(["user"])
    llm = FakeLlm()
    r = Runner(cfg, reg, ws, llm, BUILTIN_TOOLS(ws))
    res = r.run_unit("U-1", "user", {"goal": "y"})
    assert res.status == "ok", res.error
    mem = res.metrics.get("memory")
    assert mem is not None, "metrics 必须含 memory 段（选择来源）"
    assert mem["picked_by_brain"] is True


def test_memory_metrics_aggregated():
    """L3-4：聚合指标——brain 引导成功率（记忆质量评测原料）。"""
    units = [
        UnitResult(unit_id="A", domain_id="execute", status="ok",
                   metrics={"memory": {"picked_by_brain": True,
                                       "spec": "m1"}}),
        UnitResult(unit_id="B", domain_id="execute", status="ok",
                   metrics={"memory": {"picked_by_brain": True,
                                       "spec": "m1"}}),
        UnitResult(unit_id="C", domain_id="execute", status="failed",
                   metrics={"memory": {"picked_by_brain": True,
                                       "spec": "m1"}}),
    ]
    m = compute_memory_metrics(units)
    assert m["brain_picks"] == 3
    assert m["brain_pick_success_rate"] == round(2 / 3, 4), m
    assert m["brain_pick_fails"] == 1
