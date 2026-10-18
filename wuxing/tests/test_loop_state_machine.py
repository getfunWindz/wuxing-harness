"""TDD：P4 T1 单元状态机事件流（Pi Harness V2 标准——状态转换可观测）。"""
import pathlib
import tempfile

from wuxing.config import EngineConfig
from wuxing.events import UnitStateChanged
from wuxing.llm.tool_results import ToolCallResult
from wuxing.registry import DomainRegistry
from wuxing.runner import Runner
from wuxing.tools.loader import load_tools
from wuxing.workspace import Workspace


class StateProbeLlm:
    """第一轮调工具、第二轮收口的假 LLM（状态机需要多轮转换）。"""

    def __init__(self):
        self.calls = 0

    def name(self):
        return "stateprobe"

    def chat(self, messages, tools=None):
        self.calls += 1
        if self.calls == 1:
            return ToolCallResult(text="我先写产物", tool_calls=[
                {"name": "write_artifact",
                 "arguments": {"path": "p.md", "kind": "plan", "content": "x"}}])
        return "方案：完整执行计划"


def _collect_states(runner, llm):
    events = []

    def emit(e):
        if isinstance(e, UnitStateChanged):
            events.append((e.unit_id, e.domain_id, e.state))

    runner.emit_event = emit
    return events


def test_state_machine_converged_sequence():
    """成功单元：thinking→tool_executing→thinking→done（工具轮转换可观测）。"""
    cfg = EngineConfig(max_loop_rounds=6, max_unit_budget=4)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    llm = StateProbeLlm()
    r = Runner(cfg, DomainRegistry(cfg), ws, llm, load_tools(ws))
    events = _collect_states(r, llm)
    res = r.run_unit("U-1", "plan", {"goal": "plan:x"})
    assert res.status == "ok"
    states = [s for _, _, s in events]
    assert states[0] == "thinking", f"首状态必须是 thinking：{states}"
    assert "tool_executing" in states, f"工具轮必须可见：{states}"
    assert "done" in states and states[-1] == "done", f"末状态必须 done：{states}"


def test_state_machine_failed_sequence():
    """预算耗尽单元：……→failed 收尾。"""
    cfg = EngineConfig(max_loop_rounds=6, max_unit_budget=2)

    class NeverConverges:
        def name(self):
            return "never"

        def chat(self, messages, tools=None):
            return "我还在思考"  # 无 marker、无工具

    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    llm = NeverConverges()
    r = Runner(cfg, DomainRegistry(cfg), ws, llm, load_tools(ws))
    events = _collect_states(r, llm)
    res = r.run_unit("U-1", "plan", {"goal": "plan:x"})
    assert res.status == "failed"
    assert events[-1][2] == "failed", f"失败单元末状态必须 failed：{events}"


def test_state_machine_waiting_on_confirm():
    """确认挂起：thinking→waiting（人工介入可见）。"""
    cfg = EngineConfig()
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    from wuxing.confirm_gate import ConfirmGate
    reg = DomainRegistry(cfg)
    llm = StateProbeLlm()
    r = Runner(cfg, reg, ws, llm, load_tools(ws),
               confirm_gate=ConfirmGate(cfg, registry=reg), auto_confirm=False)
    events = _collect_states(r, llm)
    res = r.run_unit("U-1", "verify", {"result": "r"})
    assert res.status == "needs_confirm"
    assert events[-1][2] == "waiting", f"挂起单元末状态必须 waiting：{events}"
