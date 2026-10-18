"""G8-M2：manager 并行准入 + per-run 引擎 + 提交期认领。"""
import pathlib
import threading
import typing

import pytest

from wuxing.shell.web.manager import BusyError, EngineManager


class _Res:
    def __init__(self):
        self.status = "done"
        self.report = "完成"
        self.artifacts = []
        self.metrics = {}


class _GateEngine:
    """慢引擎：run_task 等 gate；记录实例（验证 per-run 不共享）。"""
    gate = threading.Event()
    instances: typing.ClassVar[list] = []

    def __init__(self, workdir, auto_confirm=False):
        self.workdir = pathlib.Path(workdir)
        self.auto_confirm = auto_confirm
        self.cancelled = False
        type(self).instances.append(self)

    def start_session(self, conversation_path=None):
        from wuxing.conversation import ConversationState
        from wuxing.session_api import ConversationSession
        return ConversationSession(self, ConversationState(conversation_path))

    def run_task(self, text, on_event=None, references=None, conversation=None,
                 overrides=None):
        type(self).gate.wait(5)
        return _Res()

    def resume_task(self, on_event=None):
        return _Res()

    def confirm_units(self, pairs, reason="", on_event=None):
        return _Res()

    def cancel_task(self):
        self.cancelled = True
        return True


@pytest.fixture(autouse=True)
def _reset_gate():
    _GateEngine.gate = threading.Event()
    _GateEngine.instances = []
    yield
    _GateEngine.gate.set()


def _manager(tmp_path, cap=3):
    mgr = EngineManager(engine_factory=_GateEngine, max_concurrent=8,
                        max_parallel_runs_per_ws=cap)
    (tmp_path / "ws").mkdir(exist_ok=True)
    ws = mgr.open_workspace(str(tmp_path / "ws"))["id"]
    return mgr, ws


def _theroad(mgr, ws, session):
    from wuxing.session_modes import save
    save(pathlib.Path(mgr.get_workspace(ws)["path"]), session, "theroad", "")


def _wait(mgr, run_id, timeout=5.0):
    assert mgr._runs[run_id].done.wait(timeout)


def test_two_design_sessions_run_parallel_with_per_run_engines(tmp_path):
    mgr, ws = _manager(tmp_path)
    _theroad(mgr, ws, "conversation-a.jsonl")
    _theroad(mgr, ws, "conversation-b.jsonl")
    r1 = mgr.submit(ws, "q1", session="conversation-a.jsonl")
    r2 = mgr.submit(ws, "q2", session="conversation-b.jsonl")
    assert r1 != r2
    assert len(mgr._active[ws]) == 2
    _GateEngine.gate.set()
    _wait(mgr, r1)
    _wait(mgr, r2)
    # per-run 引擎：两个 run 两个实例（不共享）
    assert len(_GateEngine.instances) == 2
    assert mgr._runs[r1].engine is not mgr._runs[r2].engine
    assert mgr._active.get(ws) is None


def test_same_session_second_submit_busy(tmp_path):
    mgr, ws = _manager(tmp_path)
    _theroad(mgr, ws, "conversation-a.jsonl")
    mgr.submit(ws, "q1", session="conversation-a.jsonl")
    with pytest.raises(BusyError, match="该会话已有活动任务"):
        mgr.submit(ws, "q2", session="conversation-a.jsonl")
    _GateEngine.gate.set()


def test_two_execution_sessions_run_parallel(tmp_path):
    """G8-M3：task_state 按 run 隔离——执行类可并行（上限内）。"""
    mgr, ws = _manager(tmp_path)   # 默认 minimal → execution
    r1 = mgr.submit(ws, "任务一", session="conversation-a.jsonl")
    r2 = mgr.submit(ws, "任务二", session="conversation-b.jsonl")
    assert len(mgr._active[ws]) == 2
    assert mgr._runs[r1].engine is not mgr._runs[r2].engine
    _GateEngine.gate.set()
    _wait(mgr, r1)
    _wait(mgr, r2)


def test_pending_confirms_other_session_not_blocked(tmp_path):
    mgr, ws = _manager(tmp_path)
    r1 = mgr.submit(ws, "挂起任务", session="conversation-a.jsonl")
    _GateEngine.gate.set()
    _wait(mgr, r1)
    mgr._runs[r1].pending_confirms = [{"unit_id": "u1"}]
    r2 = mgr.submit(ws, "新任务", session="conversation-b.jsonl")
    assert r2
    _wait(mgr, r2)


def test_overlap_warning_event(tmp_path):
    class _Hub:
        def __init__(self):
            self.events = []

        def emit(self, *args, **kwargs):
            self.events.append((args, kwargs))

        def info(self):
            return {"last_seq": 0}

    mgr, ws = _manager(tmp_path)
    mgr.hub = _Hub()
    r1 = mgr.submit(ws, "开发一个带用户登录的网站",
                    session="conversation-a.jsonl")
    r2 = mgr.submit(ws, "开发一个带用户登录的网站",
                    session="conversation-b.jsonl")
    types = [e[0][0] for e in mgr.hub.events]
    assert "task_overlap_warning" in types
    _GateEngine.gate.set()
    _wait(mgr, r1)
    _wait(mgr, r2)


def test_recovery_engine_targets_latest_run(tmp_path):
    from wuxing.protocols import UnitResult
    from wuxing.state import TaskState, run_state_path, save_state
    ws_dir = tmp_path / "rws"
    ws_dir.mkdir()
    p = run_state_path(ws_dir, "r9")
    p.parent.mkdir(parents=True)
    save_state(TaskState(task_text="待恢复", fragments=[],
                         units=[UnitResult(unit_id="u1", domain_id="execute",
                                           status="needs_confirm")],
                         artifacts=[], status="pending"), p)
    seen = {}

    class _RecEngine:
        def __init__(self, workdir, auto_confirm=False, run_id=None):
            seen["run_id"] = run_id

        def resume_task(self, on_event=None):
            return _Res()

        def cancel_task(self):
            return True

        def confirm_units(self, *args, **kwargs):
            return _Res()

    mgr = EngineManager(engine_factory=_RecEngine, max_concurrent=8)
    ws = mgr.open_workspace(str(ws_dir))["id"]
    mgr.resume_workspace(ws)
    assert seen.get("run_id") == "r9"


def test_cap_one_legacy_exclusive(tmp_path):
    mgr, ws = _manager(tmp_path, cap=1)
    _theroad(mgr, ws, "conversation-a.jsonl")
    _theroad(mgr, ws, "conversation-b.jsonl")
    mgr.submit(ws, "q1", session="conversation-a.jsonl")
    with pytest.raises(BusyError, match="已有活动任务"):
        mgr.submit(ws, "q2", session="conversation-b.jsonl")
    _GateEngine.gate.set()


def test_cap_exceeded(tmp_path):
    mgr, ws = _manager(tmp_path, cap=2)
    for s in ("a", "b", "c"):
        _theroad(mgr, ws, f"conversation-{s}.jsonl")
    mgr.submit(ws, "q1", session="conversation-a.jsonl")
    mgr.submit(ws, "q2", session="conversation-b.jsonl")
    with pytest.raises(BusyError, match="并行已达上限"):
        mgr.submit(ws, "q3", session="conversation-c.jsonl")
    _GateEngine.gate.set()


def _seed_ticketed_ws(mgr, ws):
    """写地图+规格+ready 票据（→ theroad 执行类）。"""
    from wuxing import design_state, spec_doc, tickets
    from wuxing.map_doc import write_sections
    path = pathlib.Path(mgr.get_workspace(ws)["path"])
    _theroad(mgr, ws, "conversation-a.jsonl")
    write_sections(path, destination="目标", route="- [ ] 实现")
    e = spec_doc.write(path, title="规格", sections={"problem": "p"})
    design_state.save(path, {"spec_slug": e["slug"], "spec_path": e["path"]})
    t = tickets.create(path, title="切片", acceptance=["可用"])
    tickets.publish(path)
    return path, t


def test_submit_claims_intent_tickets(tmp_path):
    from wuxing import tickets
    mgr, ws = _manager(tmp_path)
    path, t = _seed_ticketed_ws(mgr, ws)
    r1 = mgr.submit(ws, "交给执行", session="conversation-a.jsonl")
    assert tickets.find(path, t["id"])["claimed_by"] == "conversation-a.jsonl"
    _GateEngine.gate.set()
    _wait(mgr, r1)


def test_claim_intent_conflict_unit(tmp_path):
    from wuxing import tickets
    ws = tmp_path / "ws"
    ws.mkdir()
    t = tickets.create(ws, title="甲")
    tickets.publish(ws)
    tickets.claim(ws, t["id"], by="sess-a")
    with pytest.raises(BusyError, match="已被认领"):
        EngineManager._claim_intent_tickets(str(ws), "sess-b")
    EngineManager._claim_intent_tickets(str(ws), "sess-b", force=True)
    assert tickets.find(ws, t["id"])["claimed_by"] == "sess-b"


def test_rollback_submit_frees_slot(tmp_path):
    from wuxing.shell.web.manager import _Run
    mgr, ws = _manager(tmp_path)
    rid = "deadbeef0001"
    rec = _Run(rid, ws, "t")
    with mgr._lock:
        mgr._runs[rid] = rec
        mgr._active.setdefault(ws, set()).add(rid)
        mgr._ws[ws]["status"] = "running"
    mgr._rollback_submit(rid)
    assert mgr._active.get(ws) is None
    assert mgr._ws[ws]["status"] == "idle"
    assert rid not in mgr._runs


def test_snapshot_picks_latest_active_run(tmp_path):
    mgr, ws = _manager(tmp_path)
    _theroad(mgr, ws, "conversation-a.jsonl")
    _theroad(mgr, ws, "conversation-b.jsonl")
    r1 = mgr.submit(ws, "q1", session="conversation-a.jsonl")
    r2 = mgr.submit(ws, "q2", session="conversation-b.jsonl")
    snap = mgr.snapshot(ws)
    assert snap["active_run"]["run_id"] in (r1, r2)
    assert snap["active_run"]["run_id"] == r2   # 最近启动
    _GateEngine.gate.set()


def test_snapshot_latest_tie_break_by_submit_order(tmp_path):
    """E0-2 验收发现（既有 flake）：started_at 同刻（Windows 计时器粒度）→
    最近活动 run 必须按提交序裁决（不得随 set 迭代序抖动）。"""
    mgr, ws = _manager(tmp_path)
    _theroad(mgr, ws, "conversation-a.jsonl")
    _theroad(mgr, ws, "conversation-b.jsonl")
    r1 = mgr.submit(ws, "q1", session="conversation-a.jsonl")
    r2 = mgr.submit(ws, "q2", session="conversation-b.jsonl")
    mgr._runs[r1].started_at = mgr._runs[r2].started_at = 1.0  # 强制同刻
    # 可控迭代序（r1 在前）：旧实现 max 同刻取首个最大 → 错选 r1
    mgr._active[ws] = [r1, r2]
    try:
        assert mgr.snapshot(ws)["active_run"]["run_id"] == r2
    finally:
        mgr._active[ws] = {r1, r2}   # 还原 set（worker 收尾需 discard）
        _GateEngine.gate.set()


def test_active_sessions_reports_running(tmp_path):
    mgr, ws = _manager(tmp_path)
    r1 = mgr.submit(ws, "任务一", session="conversation-a.jsonl")
    assert mgr.active_sessions(ws) == {"conversation-a.jsonl"}
    _GateEngine.gate.set()
    _wait(mgr, r1)
    assert mgr.active_sessions(ws) == set()


def test_cancel_routes_to_target_run_engine(tmp_path):
    """设计 §5-7：取消只作用于目标 run。"""
    mgr, ws = _manager(tmp_path)
    r1 = mgr.submit(ws, "任务一", session="conversation-a.jsonl")
    r2 = mgr.submit(ws, "任务二", session="conversation-b.jsonl")
    mgr.cancel(r1)
    assert mgr._runs[r1].engine.cancelled is True
    assert mgr._runs[r2].engine.cancelled is False
    _GateEngine.gate.set()
    _wait(mgr, r1)
    _wait(mgr, r2)
