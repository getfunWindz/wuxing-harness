"""TDD：批量确认（壳 P1 对齐项④）——串行 + 幂等（多挂起场景）。

语义：items=[(unit_id, approve), ...]；单元已终态（非 needs_confirm）→ 跳过
（不双跑）；未知 unit_id → 预校验整体拒绝（不产生任何副作用）。
"""
import pathlib
import tempfile

import pytest

from wuxing.llm.tool_results import ToolCallResult


class CountingLlm:
    def __init__(self):
        self.calls = 0

    def name(self):
        return "counting"

    def chat(self, messages, tools=None):
        self.calls += 1
        return ToolCallResult(text="完成声明：任务已完成", tool_calls=[])


def _mk_state(wd, units, fragments):
    from wuxing.state import TaskState, save_state
    save_state(TaskState(task_text="批量确认测试", fragments=fragments,
                         units=units, status="pending"),
               wd / "task_state.json")


def _mk_engine(wd, llm=None):
    from wuxing.config import EngineConfig
    from wuxing.engine import Engine
    return Engine(cfg=EngineConfig(max_loop_rounds=2, max_unit_budget=2),
                  workdir=wd, llm=llm, auto_confirm=False)


def test_confirm_units_emits_events():
    """确认恢复路径必须转发事件（壳确认回路可见——UI 重构阶段 2.5）。"""
    from wuxing.protocols import UnitResult
    wd = pathlib.Path(tempfile.mkdtemp())
    _mk_state(wd,
              [UnitResult(unit_id="F-1", domain_id="execute",
                          status="needs_confirm")],
              [{"fragment_id": "F-1", "domain": "execute", "deps": [],
                "text": "一"}])
    eng = _mk_engine(wd, CountingLlm())
    events = []
    eng.confirm_units([("F-1", True)], reason="批准", on_event=events.append)
    names = [type(e).__name__ for e in events]
    assert "UnitStarted" in names, names
    assert "UnitDone" in names, names
    assert "TaskDone" in names, names
    done = next(e for e in events if type(e).__name__ == "UnitDone")
    assert done.unit_id == "F-1" and done.status in ("ok", "failed")


def test_confirm_reject_emits_events():
    """驳回也要进事件流（UI 可见终态；无 UnitStarted——未执行）。"""
    from wuxing.protocols import UnitResult
    wd = pathlib.Path(tempfile.mkdtemp())
    _mk_state(wd,
              [UnitResult(unit_id="F-1", domain_id="execute",
                          status="needs_confirm")],
              [{"fragment_id": "F-1", "domain": "execute", "deps": [],
                "text": "一"}])
    eng = _mk_engine(wd, CountingLlm())
    events = []
    eng.confirm_units([("F-1", False)], reason="理由",
                      on_event=events.append)
    names = [type(e).__name__ for e in events]
    assert "UnitDone" in names and "TaskDone" in names, names
    done = next(e for e in events if type(e).__name__ == "UnitDone")
    assert done.status == "rejected"


def test_confirm_units_sequential_mixed():
    from wuxing.protocols import UnitResult
    wd = pathlib.Path(tempfile.mkdtemp())
    _mk_state(wd,
              [UnitResult(unit_id="F-1", domain_id="execute",
                          status="needs_confirm"),
               UnitResult(unit_id="F-2", domain_id="execute",
                          status="needs_confirm")],
              [{"fragment_id": "F-1", "domain": "execute", "deps": [],
                "text": "一"},
               {"fragment_id": "F-2", "domain": "execute", "deps": [],
                "text": "二"}])
    eng = _mk_engine(wd, CountingLlm())
    res = eng.confirm_units([("F-1", False), ("F-2", False)], reason="批量驳回")
    unit_map = {u.unit_id: u for u in res.units}
    dump = [(u.unit_id, u.status, u.error) for u in res.units]
    assert unit_map["F-1"].status == "rejected", dump
    assert unit_map["F-2"].status == "rejected", dump
    assert res.status == "failed", (res.status, dump)


def test_confirm_units_idempotent_no_double_run():
    from wuxing.protocols import UnitResult
    wd = pathlib.Path(tempfile.mkdtemp())
    _mk_state(wd,
              [UnitResult(unit_id="F-1", domain_id="execute",
                          status="needs_confirm")],
              [{"fragment_id": "F-1", "domain": "execute", "deps": [],
                "text": "一"}])
    llm = CountingLlm()
    eng = _mk_engine(wd, llm)
    eng.confirm_units([("F-1", True)])
    calls_after_first = llm.calls
    assert calls_after_first > 0, "批准必须触发单元执行"
    res = eng.confirm_units([("F-1", True)])  # 重复——必须跳过（不双跑）
    assert llm.calls == calls_after_first, "重复确认不得重跑单元"
    unit = {u.unit_id: u for u in res.units}["F-1"]
    assert unit.status != "needs_confirm"


def test_confirm_units_unknown_raises_before_side_effects():
    from wuxing.protocols import UnitResult
    from wuxing.state import load_state
    wd = pathlib.Path(tempfile.mkdtemp())
    _mk_state(wd,
              [UnitResult(unit_id="F-1", domain_id="execute",
                          status="needs_confirm")],
              [{"fragment_id": "F-1", "domain": "execute", "deps": [],
                "text": "一"}])
    eng = _mk_engine(wd, CountingLlm())
    with pytest.raises(KeyError):
        eng.confirm_units([("NOPE", False), ("F-1", False)])
    state = load_state(wd / "task_state.json")
    unit = next(u for u in state.units if u.unit_id == "F-1")
    assert unit.status == "needs_confirm", "预校验失败不得产生副作用"
