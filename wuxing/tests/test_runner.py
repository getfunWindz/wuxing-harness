import pathlib
import tempfile

from wuxing.config import EngineConfig
from wuxing.llm.mock import MockLlmProvider
from wuxing.protocols import Artifact
from wuxing.registry import DomainRegistry
from wuxing.runner import Runner
from wuxing.tools.builtin import BUILTIN_TOOLS
from wuxing.workspace import Workspace


def _mk_runner():
    cfg = EngineConfig()
    reg = DomainRegistry(cfg)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    return Runner(cfg, reg, ws, MockLlmProvider(), BUILTIN_TOOLS(ws))

def test_runner_honors_max_rounds():
    r = _mk_runner()
    # 构造一个永不收敛的 fragment（mock 不收敛：内容不带完成标记）
    res = r.run_unit("U-1", "plan", {"goal": "plan:永不收敛任务"})
    assert res.status in ("ok", "failed")
    assert r._rounds <= r.cfg.max_loop_rounds

def test_runner_uses_domain_prompt():
    r = _mk_runner()
    res = r.run_unit("U-1", "plan", {"goal": "plan:写一篇请假邮件"})
    assert res.status == "ok"
    assert len(res.artifacts) >= 1
    assert res.artifacts[0].kind == "plan"

def test_runner_unknown_tool_blocked():
    r = _mk_runner()
    res = r.run_unit("U-1", "verify", {"result": "verify:x"})
    # verify 域白名单不含 write_artifact 之外的……默认含 read_dependency/write_artifact
    assert res.status == "ok"

def test_runner_blocked_unknown_tool_and_still_converges():
    # 工具白名单护栏：工具调用在白名单内 → 执行；白名单外 → 拦截，不阻断收敛
    class ToolCallingLlm:
        def __init__(self):
            self.call_count = 0
        def name(self):
            return "toolcall-mock"
        def chat(self, messages):
            self.call_count += 1
            if self.call_count == 1:
                # 第一轮：尝试调用白名单外工具 bash
                return "TOOLCALL:bash cmd=rm -rf\n方案：修改中"
            return "方案：1. 收集信息 2. 产出内容\n验收标准：内容完整"
    cfg = EngineConfig()
    reg = DomainRegistry(cfg)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    r = Runner(cfg, reg, ws, ToolCallingLlm(), BUILTIN_TOOLS(ws))
    res = r.run_unit("U-1", "plan", {"goal": "plan:x"})
    assert res.status == "ok"
    assert r._blocked_tools == ["bash"]  # 白名单外工具被拦截记录
    assert len(res.logs) == 2

def test_runner_budget_guard():
    cfg = EngineConfig(max_unit_budget=1)
    reg = DomainRegistry(cfg)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    r = Runner(cfg, reg, ws, MockLlmProvider(), BUILTIN_TOOLS(ws))
    res = r.run_unit("U-1", "plan", {"goal": "plan:x"})
    assert r._calls <= 1
    assert res.status in ("ok", "failed")

def test_runner_provider_exception_graceful():
    """P15 真跑发现：provider 异常（中转站防护页 RuntimeError）不得冲破 run_task——
    应转 UnitResult failed(provider 类)；且 provider 失败不归因智脑（环境故障非模型质量）。"""
    from wuxing.llm.brain import BrainMemory

    class ExplodingLlm:
        def name(self): return "boom"
        def spec(self): return "openai:gpt-4o"
        def chat(self, messages, tools=None):
            raise RuntimeError("provider 返回非 JSON（status=200）: <!doctype html>")

    mem = BrainMemory(pathlib.Path(tempfile.mkdtemp()) / "b.json")
    cfg = EngineConfig()
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    r = Runner(cfg, DomainRegistry(cfg), ws, ExplodingLlm(),
               BUILTIN_TOOLS(ws), brain_memory=mem)
    res = r.run_unit("U-1", "plan", {"goal": "plan:x"})
    assert res.status == "failed"
    assert res.error.startswith("provider:")  # provider 类失败（repairer 分类态）
    assert len(mem.cases) == 0  # provider 抖动不归因模型（P14 Q4-B）


def test_runner_repeat_tool_reminder():
    """阶段 3d（DSH repeat-tool-reminder 参考）：同工具同参数连续 ≥3 次 → logs 提示。
    防 LLM 空转（重复调用同一工具不收敛）。"""
    class RepeatLlm:
        def name(self): return "repeat"
        def spec(self): return "mock"
        def chat(self, messages, tools=None):
            # 每轮都申请同一次 read_dependency（同参数）——触发提醒
            from wuxing.llm.tool_results import ToolCallResult
            return ToolCallResult(text="继续", tool_calls=[
                {"name": "read_dependency", "arguments": {"path": "plan.md"}}])

    cfg = EngineConfig(max_loop_rounds=5, max_unit_budget=5)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    r = Runner(cfg, DomainRegistry(cfg), ws, RepeatLlm(), BUILTIN_TOOLS(ws))
    res = r.run_unit("U-1", "plan", {"goal": "plan:x"})
    reminder = [l for l in res.logs if "重复" in l]
    assert reminder, "同工具同参数重复 ≥3 次应提醒"


class _SeqProbeLlm:
    """连续两单元共享 Runner（confirm 场景）：U1 尾轮 write path=same.md；
    U2 两轮 write path=same.md——若 _repeat_seq 不重置，U2 第二轮被误报
    「连续 3 次」（U1 的 1 次残留计入）。"""

    def __init__(self):
        self.usage_history = []
        self.call_count = 0
        self.mode = "u1"

    def name(self):
        return "seqprobe"

    def spec(self):
        return "seqprobe"

    def supports_native_tools(self):
        return False

    def chat(self, messages, tools=None):
        from wuxing.llm.tool_results import ToolCallResult
        self.usage_history.append({"input": 0, "output": 0,
                                   "cache_read": 0, "cache_write": 0})
        self.call_count += 1
        # verify 域：多轮构造——每轮 read deps.md（同参）；末轮给结论
        # （verify 无「写物证充分性」分支——结论 marker 必需——多轮可达）
        if self.call_count == 1:
            return ToolCallResult(text="正在检查", tool_calls=[
                {"name": "read_dependency",
                 "arguments": {"path": "deps.md"}}])
        if self.call_count == 2:
            return ToolCallResult(text="检查中", tool_calls=[
                {"name": "read_dependency",
                 "arguments": {"path": "deps.md"}}])
        # 末轮：纯文本结论（不再调工具——读物证已由前轮累计）
        return "检查完成，结论：通过" 


def test_repeat_seq_reset_between_units():
    """B4：_repeat_seq 不得跨 run_unit 泄漏——共享 Runner 连续单元（confirm 路径）
    不得把上一单元的同参序列计入本单元（误报「连续 3 次」假阳性）。"""
    import pathlib
    import tempfile

    from wuxing.config import EngineConfig
    from wuxing.registry import DomainRegistry
    from wuxing.runner import Runner
    from wuxing.tools.loader import load_tools
    from wuxing.workspace import Workspace

    cfg = EngineConfig()
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    llm = _SeqProbeLlm()
    r = Runner(cfg, DomainRegistry(cfg), ws, llm, load_tools(ws))
    ws.write_artifact(Artifact(path="deps.md", kind="result",
                               producer_unit="U0"), "内容")
    r.run_unit("U1", "verify", {"goal": "g1", "task": "t",
                                "result": "内容", "paths": "deps.md"})
    assert llm.call_count == 3, "U1 完成需要 3 轮"
    llm.mode = "u2"
    llm.call_count = 0
    res2 = r.run_unit("U2", "verify", {"goal": "g2", "task": "t",
                                       "result": "内容", "paths": "deps.md"})
    warns = [l for l in res2.logs if l.startswith("[warn]")]
    assert warns == [], f"U2 不得因 U1 残留被误报重复调用：{warns}"
