"""TDD：任务取消（壳 P1 对齐项②）——协作式取消 + cancelled 状态 + 可续跑。

语义（设计 §3.2）：取消在**协作式检查点**生效（片段边界 / 轮次边界 /
工具批前），不 kill 线程；任务终态 `cancelled`；取消单元不视为完成 →
`resume_task` 可继续。
"""
import json
import pathlib
import tempfile
import threading

from wuxing.llm.tool_results import ToolCallResult


class SlowLlm:
    """阻塞式假 LLM：记录调用数；chat 阻塞到 release（测试放行）。"""

    def __init__(self):
        self.calls = 0
        self.started = threading.Event()
        self.release = threading.Event()
        self._lock = threading.Lock()

    def name(self):
        return "slow-test"

    def chat(self, messages, tools=None):
        with self._lock:
            self.calls += 1
        self.started.set()
        self.release.wait(timeout=10)
        return ToolCallResult(text="完成声明：任务已完成", tool_calls=[])


FRAGS = [
    {"fragment_id": "F-0001", "domain": "execute", "deps": [],
     "text": "执行步骤一", "deliverables": []},
    {"fragment_id": "F-0002", "domain": "execute", "deps": ["F-0001"],
     "text": "执行步骤二", "deliverables": []},
]


def _mk_engine(llm):
    from wuxing.config import EngineConfig
    from wuxing.engine import Engine
    wd = pathlib.Path(tempfile.mkdtemp())
    eng = Engine(cfg=EngineConfig(max_loop_rounds=3, max_unit_budget=3),
                 workdir=wd, llm=llm, auto_confirm=True)
    eng._build_fragments = lambda _text: [dict(f) for f in FRAGS]
    return eng, wd


def _run_in_thread(eng, box):
    def run():
        box["res"] = eng.run_task("取消测试任务")
    t = threading.Thread(target=run)
    t.start()
    return t


def test_cancel_between_rounds_stops_run():
    llm = SlowLlm()
    eng, wd = _mk_engine(llm)
    box = {}
    t = _run_in_thread(eng, box)
    try:
        assert llm.started.wait(5), "首个 LLM 调用必须发生"
        assert eng.cancel_task() is True, "取消必须作用于活动任务"
    finally:
        llm.release.set()
    t.join(timeout=15)
    assert not t.is_alive(), "取消后任务必须在时限内返回"
    res = box["res"]
    assert res.status == "cancelled", res.status
    assert llm.calls == 1, f"取消后不得再发起 LLM 调用（实际 {llm.calls}）"
    state = json.loads((wd / "task_state.json").read_text(encoding="utf-8"))
    assert state["status"] == "cancelled", state["status"]


def test_cancel_then_resume_continues():
    llm = SlowLlm()
    eng, _wd = _mk_engine(llm)
    box = {}
    t = _run_in_thread(eng, box)
    try:
        assert llm.started.wait(5)
        assert eng.cancel_task() is True
    finally:
        llm.release.set()
    t.join(timeout=15)
    assert box["res"].status == "cancelled"
    resumed = eng.resume_task()
    assert resumed.status != "cancelled", resumed.status
    assert resumed.units, "续跑必须产生单元结果"


def test_cancel_idempotent_without_active_run():
    llm = SlowLlm()
    eng, _wd = _mk_engine(llm)
    assert eng.cancel_task() is False, "无活动任务时取消返回 False"
    assert eng.cancel_task() is False, "重复取消安全"


def test_task_status_cancelled_priority():
    from wuxing.engine import Engine
    from wuxing.protocols import UnitResult
    units = [UnitResult(unit_id="A", domain_id="execute", status="ok"),
             UnitResult(unit_id="B", domain_id="execute", status="cancelled")]
    assert Engine._task_status(units) == "cancelled"
