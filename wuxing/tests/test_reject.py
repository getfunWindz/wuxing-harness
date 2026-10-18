"""TDD：驳回语义（壳 P1 对齐项③）——rejected 终态 + resume 不重跑 + 任务级 failed。

默认习惯（设计 §3.4）：驳回 = 终止任务（该轮不落完成记录）；被驳回单元
不再重跑；任务级状态保持 failed（不新增任务级状态），单元级 `rejected`
供 UI 区分「用户驳回」与「执行失败」。
"""
import pathlib
import tempfile

from wuxing.llm.tool_results import ToolCallResult


class CountingLlm:
    def __init__(self):
        self.calls = 0

    def name(self):
        return "counting"

    def chat(self, messages, tools=None):
        self.calls += 1
        return ToolCallResult(text="部分结果", tool_calls=[])


def _save_state(wd, fragments, units):
    from wuxing.state import TaskState, save_state
    save_state(TaskState(task_text="驳回测试", fragments=fragments, units=units,
                         status="pending"), wd / "task_state.json")


def test_confirm_reject_marks_rejected_and_task_failed():
    from wuxing.config import EngineConfig
    from wuxing.engine import Engine
    from wuxing.protocols import UnitResult
    wd = pathlib.Path(tempfile.mkdtemp())
    _save_state(wd,
                [{"fragment_id": "F-1", "domain": "execute", "deps": [],
                  "text": "步骤一"}],
                [UnitResult(unit_id="F-1", domain_id="execute",
                            status="needs_confirm")])
    eng = Engine(cfg=EngineConfig(), workdir=wd, auto_confirm=False)
    res = eng.confirm_unit("F-1", approve=False, reason="测试驳回")
    unit = {u.unit_id: u for u in res.units}["F-1"]
    assert unit.status == "rejected", unit.status
    assert res.status == "failed", res.status


def test_resume_skips_rejected_units_no_rerun():
    from wuxing.config import EngineConfig
    from wuxing.engine import Engine
    from wuxing.protocols import UnitResult
    wd = pathlib.Path(tempfile.mkdtemp())
    _save_state(wd,
                [{"fragment_id": "F-1", "domain": "execute", "deps": [],
                  "text": "步骤一"}],
                [UnitResult(unit_id="F-1", domain_id="execute",
                            status="rejected")])
    llm = CountingLlm()
    eng = Engine(cfg=EngineConfig(), workdir=wd, llm=llm, auto_confirm=True)
    res = eng.resume_task()
    assert llm.calls == 0, "被驳回单元不得重跑"
    unit = {u.unit_id: u for u in res.units}["F-1"]
    assert unit.status == "rejected"


def test_resume_runs_other_pending_but_keeps_rejected():
    from wuxing.config import EngineConfig
    from wuxing.engine import Engine
    from wuxing.protocols import UnitResult
    wd = pathlib.Path(tempfile.mkdtemp())
    _save_state(wd,
                [{"fragment_id": "F-1", "domain": "execute", "deps": [],
                  "text": "步骤一"},
                 {"fragment_id": "F-2", "domain": "execute", "deps": [],
                  "text": "步骤二"}],
                [UnitResult(unit_id="F-1", domain_id="execute",
                            status="rejected"),
                 UnitResult(unit_id="F-2", domain_id="execute",
                            status="failed")])
    llm = CountingLlm()
    eng = Engine(cfg=EngineConfig(max_loop_rounds=2, max_unit_budget=2),
                 workdir=wd, llm=llm, auto_confirm=True)
    res = eng.resume_task()
    assert llm.calls > 0, "其他 pending 单元必须执行"
    unit = {u.unit_id: u for u in res.units}["F-1"]
    assert unit.status == "rejected", "被驳回单元不得被重跑覆盖"


def test_task_status_failed_on_reject():
    from wuxing.engine import Engine
    from wuxing.protocols import UnitResult
    units = [UnitResult(unit_id="A", domain_id="execute", status="ok"),
             UnitResult(unit_id="B", domain_id="execute", status="rejected")]
    assert Engine._task_status(units) == "failed"
