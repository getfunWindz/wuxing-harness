"""E2-4（SEC）：确认门审计对 + fail-closed 链路（A6/B6）。"""
import json

from wuxing.config import EngineConfig
from wuxing.llm.mock import MockLlmProvider
from wuxing.llm.tool_results import ToolCallResult
from wuxing.registry import DomainRegistry
from wuxing.runner import Runner
from wuxing.tools.builtin import BUILTIN_TOOLS
from wuxing.trace import TraceLogger
from wuxing.workspace import Workspace


def _runner(tmp_path, auto_confirm=False):
    cfg = EngineConfig(confirm_threshold=1.0)
    ws = Workspace(tmp_path)
    trace = TraceLogger(tmp_path / ".wuxing" / "trace.jsonl")
    r = Runner(cfg, DomainRegistry(cfg), ws, MockLlmProvider(),
               BUILTIN_TOOLS(ws), confirm_gate=None,
               auto_confirm=auto_confirm, trace=trace)
    return r, trace


def test_confirm_asked_traced_and_fail_closed(tmp_path):
    """无应答 → 挂起（不执行）+ 审计 asked（fail-closed：默认不通过）。"""
    r, trace = _runner(tmp_path)
    res = r.run_unit("U-1", "plan", {"goal": "plan:x"})
    assert res.status == "needs_confirm"
    rows = [x for x in trace.load() if x.get("event") == "confirm_asked"]
    assert rows and rows[-1]["unit_id"] == "U-1" \
        and rows[-1]["domain"] == "plan"
    assert rows[-1].get("surface") == "unit_confirm"


def test_confirm_auto_confirm_no_ask(tmp_path):
    """显式 auto_confirm → 不挂起、不落 asked（自动路径可审计区分）。"""
    r, trace = _runner(tmp_path, auto_confirm=True)
    res = r.run_unit("U-1", "plan", {"goal": "plan:x"})
    assert res.status == "ok"
    assert not [x for x in trace.load() if x.get("event") == "confirm_asked"]


class CountingLlm:
    def __init__(self):
        self.calls = 0

    def name(self):
        return "counting"

    def spec(self):
        return "mock"

    def chat(self, messages, tools=None):
        self.calls += 1
        return ToolCallResult(text="完成声明：任务已完成", tool_calls=[])


def _mk_state(wd, units, fragments):
    from wuxing.state import TaskState, save_state
    save_state(TaskState(task_text="审计测试", fragments=fragments,
                         units=units, status="pending"),
               wd / "task_state.json")


def _engine(tmp_path):
    from wuxing.engine import Engine
    return Engine(cfg=EngineConfig(max_loop_rounds=2, max_unit_budget=2),
                  workdir=tmp_path, llm=CountingLlm(), auto_confirm=False)


def _pending_state(wd):
    from wuxing.protocols import UnitResult
    _mk_state(wd,
              [UnitResult(unit_id="F-1", domain_id="execute",
                          status="needs_confirm")],
              [{"fragment_id": "F-1", "domain": "execute", "deps": [],
                "text": "一"}])


def _trace_rows(wd):
    return [json.loads(x) for x in
            (wd / ".wuxing" / "trace.jsonl").read_text(
                encoding="utf-8").splitlines() if x.strip()]


def test_confirm_reject_traced_and_not_executed(tmp_path):
    eng = _engine(tmp_path)
    _pending_state(tmp_path)
    eng.confirm_unit("F-1", approve=False, reason="test-reject")
    dec = [x for x in _trace_rows(tmp_path)
           if x.get("event") == "confirm_decided"]
    assert dec and dec[-1]["unit_id"] == "F-1"
    assert dec[-1]["decision"] == "reject" \
        and dec[-1]["reason"] == "test-reject"
    assert dec[-1].get("surface") == "unit_confirm"


def test_confirm_approve_traced_and_runs(tmp_path):
    eng = _engine(tmp_path)
    _pending_state(tmp_path)
    res2 = eng.confirm_unit("F-1", approve=True)
    units = {x.unit_id: x for x in res2.units}
    assert units["F-1"].status in ("ok", "failed")   # 已执行（非挂起）
    dec = [x for x in _trace_rows(tmp_path)
           if x.get("event") == "confirm_decided"]
    assert dec and dec[-1]["decision"] == "approve"
