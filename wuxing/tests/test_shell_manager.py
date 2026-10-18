"""TDD：EngineManager（壳 P1 · B3）——工作区注册/任务线程/并发上限/命令路由。

设计 §3：工作区=并发单位（每工作区一个活动任务）；全局并发上限（默认 2，
P1 超出拒绝）；引擎懒构造；事件桥接 EventHub；confirm/resume/cancel 路由。
"""
import pathlib
import threading

import pytest

from wuxing.shell.web.hub import EventHub


# ---- 假引擎（事件对象名与 wuxing.events 对齐——管理器按类名映射） ----
class UnitStarted:
    def __init__(self, unit_id, domain_id):
        self.unit_id, self.domain_id = unit_id, domain_id


class UnitDone:
    def __init__(self, unit_id, domain_id, status):
        self.unit_id, self.domain_id, self.status = unit_id, domain_id, status


class UnitNeedsConfirm:
    def __init__(self, unit_id, domain_id, reason="", impact=None, view=None):
        self.unit_id, self.domain_id, self.reason = unit_id, domain_id, reason
        self.impact = impact or {}
        self.view = view or {}


class TaskDone:
    def __init__(self, status):
        self.status = status


class _Result:
    def __init__(self, status="done", report="报告", artifacts=None,
                 metrics=None, units=None):
        self.status = status
        self.report = report
        self.artifacts = artifacts or []
        self.metrics = metrics or {}
        self.units = units or []


class _Unit:
    def __init__(self, unit_id, domain_id, status):
        self.unit_id, self.domain_id, self.status = unit_id, domain_id, status


class FakeEngine:
    def __init__(self, workdir, auto_confirm=False, mode="done",
                 auto_release=True):
        self.workdir = workdir
        self.auto_confirm = auto_confirm
        self.mode = mode
        self.started = threading.Event()
        self.release = threading.Event()
        if auto_release:
            self.release.set()
        self.confirm_calls = []
        self.cancel_called = False
        self.resume_calls = 0
        self.run_overrides = []  # 二期批 1：override 透传记录

    def start_session(self, conversation_path=None):
        """修复①（2026-09-20）：manager 经引擎公开 API 建会话——测试桩用真实实现。"""
        from wuxing.conversation import ConversationState
        from wuxing.session_api import ConversationSession
        return ConversationSession(self, ConversationState(conversation_path))

    def run_task(self, text, on_event=None, references=None, conversation=None,
                 overrides=None):
        self.run_overrides = list(overrides or [])
        if on_event:
            on_event(UnitStarted("F-1", "execute"))
        self.started.set()
        self.release.wait(5)
        if self.mode == "pending":
            if on_event:
                on_event(UnitNeedsConfirm("F-1", "execute", "窗口切换待确认",
                                          impact={"tools": ["bash"],
                                                  "summary": "要点摘要"},
                                          view={
                                              "title": "有一个步骤需要你点头后才会继续。",
                                              "object": "涉及内容：要点摘要",
                                              "allow_effect": "允许后：这一步会按计划执行。",
                                              "deny_effect": "拒绝后：这一步会被标记为「已驳回」。",
                                              "action_hint": "拿不准时，拒绝是安全的。",
                                              "trigger": "为什么问你：演示。",
                                              "position": "",
                                              "details": {},
                                              "options": ["批准", "驳回"]}))
            return _Result(status="pending", report="待确认")
        if on_event:
            on_event(UnitDone("F-1", "execute", "ok"))
            on_event(TaskDone("done"))
        return _Result(status="done", units=[_Unit("F-1", "execute", "ok")])

    def confirm_units(self, items, reason="", on_event=None):
        self.confirm_calls.append((list(items), reason))
        for uid, approve in items:
            if on_event:
                on_event(UnitStarted(uid, "execute"))
                on_event(UnitDone(uid, "execute", "ok" if approve else "rejected"))
        if on_event:
            on_event(TaskDone("done"))
        return _Result(status="done", report="确认后")

    def resume_task(self, on_event=None):
        self.resume_calls += 1
        return _Result(status="done", report="续跑")

    def cancel_task(self):
        self.cancel_called = True
        return True


class Factory:
    def __init__(self, mode="done", auto_release=True):
        self.mode = mode
        self.auto_release = auto_release
        self.engines = {}
        self.last = None

    def __call__(self, workdir, auto_confirm):
        eng = FakeEngine(workdir, auto_confirm, mode=self.mode,
                         auto_release=self.auto_release)
        self.engines[str(workdir)] = eng
        self.last = eng
        return eng


def _mk_manager(tmp_path, fac=None, **kw):
    from wuxing.shell.web.manager import EngineManager
    return EngineManager(hub=EventHub(), engine_factory=fac or Factory(),
                         state_path=tmp_path / "ws.json", **kw)


def _mk_ws(tmp_path, mgr, name="proj"):
    wd = tmp_path / name
    wd.mkdir(exist_ok=True)
    return mgr.open_workspace(str(wd))


def test_open_list_close_and_persistence(tmp_path):
    mgr = _mk_manager(tmp_path)
    ws = _mk_ws(tmp_path, mgr)
    assert ws["name"] == "proj" and ws["id"]
    assert [w["id"] for w in mgr.list_workspaces()] == [ws["id"]]
    assert (tmp_path / "ws.json").exists(), "服务侧状态必须持久化"
    mgr2 = _mk_manager(tmp_path)
    assert [w["id"] for w in mgr2.list_workspaces()] == [ws["id"]], \
        "新实例必须恢复工作区列表"
    mgr.close_workspace(ws["id"])
    assert mgr.list_workspaces() == []


def test_submit_runs_task_and_emits_events(tmp_path):
    fac = Factory()
    mgr = _mk_manager(tmp_path, fac=fac)
    ws = _mk_ws(tmp_path, mgr)
    sub, _, _ = mgr.hub.subscribe()
    run_id = mgr.submit(ws["id"], "做个任务")
    rec = mgr.wait(run_id, timeout=5)
    assert rec["status"] == "done", rec
    assert rec["result"]["report"] == "报告"
    types = []
    while True:
        ev = sub.get(timeout=0.05)
        if ev is None:
            break
        types.append((ev["type"], ev["workspace_id"], ev["run_id"]))
    assert ("task_submitted", ws["id"], run_id) in types
    assert ("unit_started", ws["id"], run_id) in types
    assert ("unit_done", ws["id"], run_id) in types
    assert ("task_done", ws["id"], run_id) in types
    snap = mgr.snapshot(ws["id"])
    assert snap["workspace"]["id"] == ws["id"]
    assert snap["active_run"] is None
    assert snap["result"]["status"] == "done"
    assert snap["last_seq"] >= 4


def test_snapshot_exposes_task_text_for_replay(tmp_path):
    """快照必须能提供最近任务文本与 run_id（前端重载后的流/悬浮卡回放用）。"""
    mgr = _mk_manager(tmp_path)
    ws = _mk_ws(tmp_path, mgr)
    run_id = mgr.submit(ws["id"], "回放用任务文本")
    mgr.wait(run_id, timeout=5)
    snap = mgr.snapshot(ws["id"])
    assert snap["task_text"] == "回放用任务文本"
    assert snap["run_id"] == run_id


def test_snapshot_exposes_unit_summaries_for_replay(tmp_path):
    """快照携带碎片摘要（unit_id/domain/status）——卡片网格重载后可回放。"""
    mgr = _mk_manager(tmp_path)
    ws = _mk_ws(tmp_path, mgr)
    run_id = mgr.submit(ws["id"], "碎片回放")
    mgr.wait(run_id, timeout=5)
    snap = mgr.snapshot(ws["id"])
    assert snap["units"] == [
        {"unit_id": "F-1", "domain_id": "execute", "status": "ok",
         "failure_class": ""}]  # S1-C：快照携带失败分类（还原分类标签用）


def test_artifact_rows_carry_mtime_from_workspace(tmp_path):
    """A6-T1（W1）：产物行携带 mtime——工作区内 stat；缺失/越界 = 0.0（不造假）。"""

    class _Art:
        def __init__(self, path, kind="md"):
            self.path, self.kind = path, kind

    class _Eng(FakeEngine):
        def run_task(self, text, on_event=None, references=None,
                     conversation=None, overrides=None):
            wd = pathlib.Path(self.workdir)
            (wd / "made.md").write_text("x", encoding="utf-8")
            res = _Result(status="done", artifacts=[
                _Art("made.md"), _Art("ghost.md"), _Art("../outside.md")])
            res.units = [_Unit("F-1", "execute", "ok")]
            if on_event:
                on_event(TaskDone("done"))
            return res

    from wuxing.shell.web.manager import EngineManager
    mgr = EngineManager(hub=EventHub(),
                        engine_factory=lambda wd, ac: _Eng(wd, ac),
                        state_path=tmp_path / "ws.json")
    ws = _mk_ws(tmp_path, mgr)
    wd = pathlib.Path(ws["path"])
    (tmp_path / "outside.md").write_text("o", encoding="utf-8")
    rid = mgr.submit(ws["id"], "产物元数据")
    rec = mgr.wait(rid, timeout=5)
    rows = {a["path"]: a for a in rec["result"]["artifacts"]}
    expected = (wd / "made.md").stat().st_mtime
    assert rows["made.md"]["mtime"] == expected
    assert rows["ghost.md"]["mtime"] == 0.0      # 文件缺失 → 0.0
    assert rows["../outside.md"]["mtime"] == 0.0  # 越界不得泄漏
    # 快照与运行记录同源（重连首屏）
    snap = mgr.snapshot(ws["id"])
    assert snap["result"]["artifacts"][0]["mtime"] == expected


def test_submit_override_forwarded(tmp_path):
    """override 经 submit → 会话 API → 引擎透传（显式链路，不吞参数）。"""
    fac = Factory()
    mgr = _mk_manager(tmp_path, fac=fac)
    ws = _mk_ws(tmp_path, mgr)
    rid = mgr.submit(ws["id"], "覆盖任务", session="conversation-o.jsonl",
                     override="no_map")
    mgr.wait(rid, timeout=5)
    assert fac.last.run_overrides == ["no_map"]
    rid2 = mgr.submit(ws["id"], "普通任务")
    mgr.wait(rid2, timeout=5)
    assert fac.last.run_overrides == []


def test_snapshot_exposes_run_session_for_scoping(tmp_path):
    """快照携带 run 所属会话——前端据此把任务流限定到所属会话（修会话串台）。

    根因（2026-09-25）：快照只给最近 run 的 task_text/result 而不给会话归属，
    切到会话 A 时会话 B 的任务流仍显示。
    """
    mgr = _mk_manager(tmp_path)
    ws = _mk_ws(tmp_path, mgr)
    run_id = mgr.submit(ws["id"], "会话任务", session="conversation-a.jsonl")
    mgr.wait(run_id, timeout=5)
    snap = mgr.snapshot(ws["id"])
    assert snap["session"] == "conversation-a.jsonl"
    assert snap["run_id"] == run_id
    # 另一会话的新 run 接管「最近 run」归属
    run2 = mgr.submit(ws["id"], "另一会话任务", session="conversation-b.jsonl")
    mgr.wait(run2, timeout=5)
    assert mgr.snapshot(ws["id"])["session"] == "conversation-b.jsonl"


def test_task_submitted_event_carries_session(tmp_path):
    """task_submitted 事件带会话名——前端提交即建立会话归属（不依赖响应先后）。"""
    mgr = _mk_manager(tmp_path)
    ws = _mk_ws(tmp_path, mgr)
    sub, _, _ = mgr.hub.subscribe()
    mgr.submit(ws["id"], "事件任务", session="conversation-c.jsonl")
    ev = sub.get(timeout=1)
    while ev is not None and ev["type"] != "task_submitted":
        ev = sub.get(timeout=0.05)
    assert ev is not None, "应收到 task_submitted 事件"
    assert ev["data"]["session"] == "conversation-c.jsonl"


def test_task_history_records_finished_runs(tmp_path):
    """任务历史（壳侧日志）：完成即落盘——含状态/起止时间/产物数；新的在前。"""
    mgr = _mk_manager(tmp_path)
    ws = _mk_ws(tmp_path, mgr)
    r1 = mgr.submit(ws["id"], "任务一")
    mgr.wait(r1, timeout=5)
    r2 = mgr.submit(ws["id"], "任务二")
    mgr.wait(r2, timeout=5)
    hist = mgr.history(ws["id"])
    assert [h["task_text"] for h in hist] == ["任务二", "任务一"]
    top = hist[0]
    assert top["run_id"] == r2 and top["status"] == "done"
    assert top["ended_at"] >= top["started_at"]
    assert "artifacts" in top


def test_task_history_survives_restart(tmp_path):
    """历史落盘：新管理器实例仍能读到（跨重启）。"""
    mgr = _mk_manager(tmp_path)
    ws = _mk_ws(tmp_path, mgr)
    rid = mgr.submit(ws["id"], "跨重启任务")
    mgr.wait(rid, timeout=5)
    mgr2 = _mk_manager(tmp_path)
    hist = mgr2.history(ws["id"])
    assert hist and hist[0]["task_text"] == "跨重启任务"


def test_confirm_bridges_events_and_cleans_pending(tmp_path):
    """确认回路：恢复执行的事件必须桥接到壳；挂起项异步清理（阶段 2.5）。"""
    import time as _t
    fac = Factory(mode="pending")
    mgr = _mk_manager(tmp_path, fac=fac)
    ws = _mk_ws(tmp_path, mgr)
    sub, _, _ = mgr.hub.subscribe()
    rid = mgr.submit(ws["id"], "确认任务")
    mgr.wait(rid, timeout=5)
    assert mgr.snapshot(ws["id"])["pending_confirms"], "应先挂起"
    mgr.confirm(rid, [("F-1", True)], reason="批准")
    got = []
    deadline = _t.time() + 3
    while _t.time() < deadline:
        ev = sub.get(timeout=0.1)
        if ev is None:
            break
        got.append(ev["type"])
        if "task_done" in got:
            break
    assert "unit_done" in got, got
    deadline = _t.time() + 3
    while _t.time() < deadline:
        if mgr.snapshot(ws["id"])["pending_confirms"] == []:
            break
        _t.sleep(0.05)
    snap = mgr.snapshot(ws["id"])
    assert snap["pending_confirms"] == []
    assert snap["result"]["status"] == "done", "确认后的结果必须同步进内存快照"


class UnitNeedsAnswer:
    def __init__(self, unit_id, domain_id, question_id, questions=None):
        self.unit_id, self.domain_id = unit_id, domain_id
        self.question_id = question_id
        self.questions = questions or []


class QuestionAnswered:
    def __init__(self, unit_id, question_id, answer, source="text"):
        self.unit_id, self.question_id = unit_id, question_id
        self.answer, self.source = answer, source


def test_answer_bridges_events_and_cleans_pending(tmp_path):
    """A10 答复回路：pending_answers 登记/清理；答复路由到引擎；事件桥接。"""
    import time as _t

    class _AskEng(FakeEngine):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self.answers = []

        def run_task(self, text, on_event=None, references=None,
                     conversation=None, overrides=None):
            if on_event:
                on_event(UnitStarted("F-1", "execute"))
                on_event(UnitNeedsAnswer(
                    "F-1", "execute", "ask-F-1-1",
                    [{"title": "格式？", "options": ["md", "txt"],
                      "multi": False}]))
                on_event(TaskDone("pending"))
            res = _Result(status="pending")
            res.units = [_Unit("F-1", "execute", "needs_answer")]
            return res

        def answer_unit(self, unit_id, question_id, answer, source="text",
                        reason="", on_event=None):
            self.answers.append((unit_id, question_id, answer, source))
            if on_event:
                on_event(QuestionAnswered(unit_id, question_id, answer, source))
                on_event(UnitDone(unit_id, "execute", "ok"))
                on_event(TaskDone("done"))
            res = _Result(status="done")
            res.units = [_Unit(unit_id, "execute", "ok")]
            return res

    from wuxing.shell.web.manager import EngineManager
    engs: list = []

    def _factory(wd, ac):
        eng = _AskEng(wd, ac)
        engs.append(eng)
        return eng

    mgr = EngineManager(hub=EventHub(), engine_factory=_factory,
                        state_path=tmp_path / "ws.json")
    ws = _mk_ws(tmp_path, mgr)
    sub, _, _ = mgr.hub.subscribe()
    rid = mgr.submit(ws["id"], "提问任务")
    mgr.wait(rid, timeout=5)
    snap = mgr.snapshot(ws["id"])
    assert snap["pending_answers"], "应先登记待答问题"
    assert snap["pending_answers"][0]["question_id"] == "ask-F-1-1"
    while sub.get(timeout=0.05) is not None:
        pass   # 清空初始事件（提交/挂起阶段）——后续只断言答复阶段事件
    mgr.answer(rid, "F-1", "ask-F-1-1", "md", source="option")
    got = []
    deadline = _t.time() + 3
    while _t.time() < deadline:
        ev = sub.get(timeout=0.1)
        if ev is None:
            break
        got.append(ev["type"])
        if "task_done" in got:
            break
    assert "question_answered" in got and "unit_done" in got, got
    assert engs[-1].answers == [("F-1", "ask-F-1-1", "md", "option")]
    deadline = _t.time() + 3
    while _t.time() < deadline:
        if mgr.snapshot(ws["id"])["pending_answers"] == []:
            break
        _t.sleep(0.05)
    snap = mgr.snapshot(ws["id"])
    assert snap["pending_answers"] == []
    assert snap["result"]["status"] == "done", "答复后的结果必须同步进快照"


def test_confirm_resume_updates_history_status(tmp_path):
    """2026-10-01 真机 P2：确认续跑完成后，壳任务历史必须从 pending 更新为
    最终状态（否则历史/对话永久显示 pending——用户判定「记录没保留/丢失」）。

    现场：run「执行」「你只生产了报告…」磁盘 task_state=done，但
    tasks.jsonl 行与对话行停留 pending（确认 worker 未补写历史）。"""
    import time as _t
    fac = Factory(mode="pending")
    mgr = _mk_manager(tmp_path, fac=fac)
    ws = _mk_ws(tmp_path, mgr)
    rid = mgr.submit(ws["id"], "确认任务")
    mgr.wait(rid, timeout=5)
    assert mgr.history(ws["id"])[0]["status"] == "pending"
    mgr.confirm(rid, [("F-1", True)], reason="批准")
    deadline = _t.time() + 5
    while _t.time() < deadline:
        if mgr.snapshot(ws["id"]).get("active_run") is None:
            break
        _t.sleep(0.05)
    hist = mgr.history(ws["id"])
    assert hist[0]["run_id"] == rid
    assert hist[0]["status"] != "pending", f"恢复后历史应更新：{hist[0]}"
    assert len([h for h in hist if h["run_id"] == rid]) == 1, "同 run 不得重复行"


def test_confirm_unknown_unit_rejected(tmp_path):
    """未知/已处理单元 → NotFoundError（同步预校验，不产生副作用）。"""
    from wuxing.shell.web.manager import NotFoundError
    fac = Factory(mode="pending")
    mgr = _mk_manager(tmp_path, fac=fac)
    ws = _mk_ws(tmp_path, mgr)
    rid = mgr.submit(ws["id"], "确认任务")
    mgr.wait(rid, timeout=5)
    with pytest.raises(NotFoundError):
        mgr.confirm(rid, [("F-nope", True)], reason="批准")


def test_open_workspace_custom_name(tmp_path):
    """工作区支持自定义名称（新建对话框·直接输入路径时可命名）。"""
    mgr = _mk_manager(tmp_path)
    ws = _mk_ws(tmp_path, mgr)
    ws2 = mgr.open_workspace(ws["path"], name="我的项目")
    assert ws2["name"] == "我的项目"
    mgr2 = _mk_manager(tmp_path)
    assert mgr2.list_workspaces()[0]["name"] == "我的项目", "名称需持久化"


def test_submit_allowed_other_session_while_pending_confirms(tmp_path):
    """G8-M3：task_state 按 run 隔离——他会话挂起确认不阻塞新 run。"""
    fac = Factory(mode="pending")
    mgr = _mk_manager(tmp_path, fac=fac)
    ws = _mk_ws(tmp_path, mgr)
    rid = mgr.submit(ws["id"], "挂起任务")
    mgr.wait(rid, timeout=5)
    assert mgr.snapshot(ws["id"])["pending_confirms"]
    rid2 = mgr.submit(ws["id"], "新任务")   # 不同（自动）会话 → 允许
    mgr.wait(rid2, timeout=5)


def test_busy_same_workspace_and_global_cap(tmp_path):
    from wuxing.shell.web.manager import BusyError
    fac = Factory(auto_release=False)
    mgr = _mk_manager(tmp_path, fac=fac, max_concurrent=1)
    ws1 = _mk_ws(tmp_path, mgr, "a")
    ws2 = _mk_ws(tmp_path, mgr, "b")
    r1 = mgr.submit(ws1["id"], "任务一")
    assert fac.engines[str(tmp_path / "a")].started.wait(5)
    with pytest.raises(BusyError):
        mgr.submit(ws1["id"], "同工作区第二任务")
    with pytest.raises(BusyError):
        mgr.submit(ws2["id"], "跨工作区超并发上限")
    with pytest.raises(BusyError):
        mgr.close_workspace(ws1["id"])
    fac.engines[str(tmp_path / "a")].release.set()
    assert mgr.wait(r1, timeout=5)["status"] == "done"
    r2 = mgr.submit(ws2["id"], "任务二")
    fac.engines[str(tmp_path / "b")].release.set()
    assert mgr.wait(r2, timeout=5)["status"] == "done"


def test_confirm_resume_cancel_routing(tmp_path):
    import time as _t
    fac = Factory(mode="pending")
    mgr = _mk_manager(tmp_path, fac=fac)
    ws = _mk_ws(tmp_path, mgr)
    run_id = mgr.submit(ws["id"], "任务")
    mgr.wait(run_id, timeout=5)
    mgr.confirm(run_id, [("F-1", True)], reason="批准")
    deadline = _t.time() + 3
    while _t.time() < deadline and not fac.last.confirm_calls:
        _t.sleep(0.05)
    assert fac.last.confirm_calls == [([("F-1", True)], "批准")]
    mgr.resume(run_id)
    deadline = _t.time() + 3
    while _t.time() < deadline and fac.last.resume_calls < 1:
        _t.sleep(0.05)
    assert fac.last.resume_calls >= 1
    mgr.cancel(run_id)
    assert fac.last.cancel_called is True


def test_pending_confirms_tracked_and_cleared(tmp_path):
    fac = Factory(mode="pending")
    mgr = _mk_manager(tmp_path, fac=fac)
    ws = _mk_ws(tmp_path, mgr)
    run_id = mgr.submit(ws["id"], "任务")
    mgr.wait(run_id, timeout=5)
    snap = mgr.snapshot(ws["id"])
    assert snap["result"]["status"] == "pending"
    assert snap["pending_confirms"], "挂起确认必须登记"
    unit = snap["pending_confirms"][0]["unit_id"]
    assert snap["pending_confirms"][0].get("impact", {}).get("tools") == ["bash"], \
        "影响清单必须随挂起投影透出"
    mgr.confirm(run_id, [(unit, False)], reason="驳回")
    import time as _t
    deadline = _t.time() + 3
    while _t.time() < deadline:
        if mgr.snapshot(ws["id"])["pending_confirms"] == []:
            break
        _t.sleep(0.05)
    snap2 = mgr.snapshot(ws["id"])
    assert snap2["pending_confirms"] == [], "确认处理后必须清除挂起"


def test_pending_confirms_carry_view(tmp_path):
    fac = Factory(mode="pending")
    mgr = _mk_manager(tmp_path, fac=fac)
    ws = _mk_ws(tmp_path, mgr)
    run_id = mgr.submit(ws["id"], "任务")
    mgr.wait(run_id, timeout=5)
    snap = mgr.snapshot(ws["id"])
    view = snap["pending_confirms"][0].get("view") or {}
    assert view.get("title"), "四要素视图必须随快照透出"
    assert view.get("allow_effect") and view.get("deny_effect")


def test_rollback_clears_engine_state_and_marks_history(tmp_path):
    """回滚（用户验收）：引擎状态清除（不可续跑）+ 历史标记 rolled_back；
    产物默认保留，显式 delete_artifacts 才删（且限 workdir 内）。"""
    import pathlib as _p

    class _Art:
        def __init__(self, path):
            self.path = path
            self.kind = "md"

    class _Eng2(FakeEngine):
        def run_task(self, text, on_event=None, references=None, conversation=None,
                     overrides=None):
            wd = _p.Path(self.workdir)
            (wd / "made.md").write_text("x", encoding="utf-8")
            (wd / "keep.md").write_text("y", encoding="utf-8")
            res = _Result(status="done", artifacts=[_Art("made.md")])
            res.units = [_Unit("F-1", "execute", "ok")]
            if on_event:
                on_event(TaskDone("done"))
            return res

    fac = Factory()
    fac.engines = {}
    from wuxing.shell.web.manager import EngineManager
    mgr = EngineManager(hub=EventHub(), engine_factory=lambda wd, ac: _Eng2(wd, ac),
                        state_path=tmp_path / "ws.json")
    ws = _mk_ws(tmp_path, mgr)
    wd = _p.Path(ws["path"])
    (wd / "task_state.json").write_text("{}", encoding="utf-8")
    rid = mgr.submit(ws["id"], "回滚任务")
    mgr.wait(rid, timeout=5)

    out = mgr.rollback(rid)
    assert out["ok"] is True
    assert not (wd / "task_state.json").exists(), "引擎状态必须清除（不可续跑）"
    assert (wd / "made.md").is_file(), "默认产物保留"
    hist = mgr.history(ws["id"])
    assert hist and hist[0]["status"] == "rolled_back"
    # 显式删产物
    rid2 = mgr.submit(ws["id"], "回滚并删产物")
    mgr.wait(rid2, timeout=5)
    out2 = mgr.rollback(rid2, delete_artifacts=True)
    assert out2["removed_artifacts"] == ["made.md"]
    assert not (wd / "made.md").exists()
    assert (wd / "keep.md").is_file(), "非本任务产物不得删除"


def test_purge_history_removes_run_lines(tmp_path):
    mgr = _mk_manager(tmp_path)
    ws = _mk_ws(tmp_path, mgr)
    rid = mgr.submit(ws["id"], "待清理任务")
    mgr.wait(rid, timeout=5)
    assert mgr.history(ws["id"])
    removed = mgr.purge_history(rid)
    assert removed >= 1
    assert mgr.history(ws["id"]) == []


# ---- 工作区文件夹（验收迭代 3 · 4b：IDE 式收纳） ----

def test_folders_create_assign_and_list(tmp_path):
    """建文件夹 → 工作区归入 → 列表携带 folder 字段。"""
    mgr = _mk_manager(tmp_path)
    ws = _mk_ws(tmp_path, mgr)
    f = mgr.create_folder("前端")
    assert f["id"] and f["name"] == "前端" and f["collapsed"] is False
    mgr.set_workspace_folder(ws["id"], f["id"])
    assert mgr.list_folders() == [f]
    listed = mgr.list_workspaces()
    assert listed[0]["folder"] == f["id"]


def test_folders_persist_rename_collapse(tmp_path):
    """文件夹与归属跨重启持久化；重命名/折叠生效。"""
    mgr = _mk_manager(tmp_path)
    ws = _mk_ws(tmp_path, mgr)
    f = mgr.create_folder("组A")
    mgr.update_folder(f["id"], name="组B", collapsed=True)
    mgr.set_workspace_folder(ws["id"], f["id"])

    mgr2 = _mk_manager(tmp_path)
    folders = mgr2.list_folders()
    assert len(folders) == 1
    assert folders[0]["name"] == "组B" and folders[0]["collapsed"] is True
    assert mgr2.list_workspaces()[0]["folder"] == f["id"]


def test_folders_delete_unassigns_workspaces(tmp_path):
    """删文件夹 → 内含工作区回到未分组（不删除工作区）。"""
    mgr = _mk_manager(tmp_path)
    ws = _mk_ws(tmp_path, mgr)
    f = mgr.create_folder("临时")
    mgr.set_workspace_folder(ws["id"], f["id"])
    mgr.delete_folder(f["id"])
    assert mgr.list_folders() == []
    assert mgr.list_workspaces()[0]["folder"] is None


def test_folders_unknown_ids_rejected(tmp_path):
    """未知文件夹/工作区 → 明确报错（不静默）。"""
    from wuxing.shell.web.manager import NotFoundError
    mgr = _mk_manager(tmp_path)
    ws = _mk_ws(tmp_path, mgr)
    with pytest.raises(NotFoundError):
        mgr.set_workspace_folder(ws["id"], "nope")
    with pytest.raises(NotFoundError):
        mgr.update_folder("nope", name="x")
    with pytest.raises(NotFoundError):
        mgr.delete_folder("nope")


def test_folders_move_out_and_empty_name_rejected(tmp_path):
    """移出文件夹（folder=None）与空名字拒绝。"""
    mgr = _mk_manager(tmp_path)
    ws = _mk_ws(tmp_path, mgr)
    f = mgr.create_folder("组")
    mgr.set_workspace_folder(ws["id"], f["id"])
    mgr.set_workspace_folder(ws["id"], None)
    assert mgr.list_workspaces()[0]["folder"] is None
    with pytest.raises(ValueError):
        mgr.create_folder("   ")


def test_new_observe_events_snake_case_mapping():
    """阶段 4：新事件类名 → 壳事件名（前端 EventSource 类型契约）。"""
    from wuxing.shell.web.manager import _snake
    assert _snake("SafetyBlocked") == "safety_blocked"
    assert _snake("FscAudit") == "fsc_audit"
    assert _snake("FscSwitch") == "fsc_switch"


def test_submit_references_forwarded_to_engine(tmp_path):
    """阶段 5（⑧）：壳提交的 references 透传到引擎 run_task。"""
    from wuxing.shell.web.manager import EngineManager
    seen = {}

    class Eng:
        def start_session(self, conversation_path=None):
            from wuxing.conversation import ConversationState
            from wuxing.session_api import ConversationSession
            return ConversationSession(self, ConversationState(conversation_path))

        def run_task(self, text, on_event=None, references=None, conversation=None,
                     overrides=None):
            seen["references"] = references
            return _Result(status="done")

        def confirm_units(self, items, reason="", on_event=None):
            return _Result(status="done")

        def resume_task(self, on_event=None):
            return _Result(status="done")

    wd = tmp_path / "proj"
    wd.mkdir()
    mgr = EngineManager(hub=EventHub(), engine_factory=lambda w, a: Eng(),
                        state_path=tmp_path / "ws.json")
    ws = mgr.open_workspace(str(wd))
    rid = mgr.submit(ws["id"], "任务", references=["a.md"])
    mgr.wait(rid, timeout=5)
    assert seen.get("references") == ["a.md"]


def test_save_state_retries_transient_oserror(tmp_path, monkeypatch):
    """Windows flake 修复：os.replace 偶发占用 → 重试后状态仍持久化。"""
    import os as os_mod
    calls = {"n": 0}
    real_replace = os_mod.replace

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError("transient lock")
        return real_replace(src, dst)

    monkeypatch.setattr(os_mod, "replace", flaky)
    mgr = _mk_manager(tmp_path)
    _mk_ws(tmp_path, mgr)
    mgr.create_folder("组A")
    monkeypatch.setattr(os_mod, "replace", real_replace)
    mgr2 = _mk_manager(tmp_path)
    assert [f["name"] for f in mgr2.list_folders()] == ["组A"]


# ---- M7 #8（A3）：挂起确认重启恢复 ----

def _write_pending_state(ws_path, unit_id="R-1"):
    import json as _json
    (pathlib.Path(ws_path) / "task_state.json").write_text(_json.dumps({
        "task_text": "恢复演示",
        "fragments": [{"fragment_id": unit_id, "domain": "execute", "deps": []}],
        "units": [{"unit_id": unit_id, "domain_id": "execute",
                   "status": "needs_confirm"}],
        "artifacts": [], "status": "pending",
    }, ensure_ascii=False), encoding="utf-8")


def test_snapshot_reports_pending_resume(tmp_path):
    """重启后（内存无 run）快照携带 pending_resume（磁盘 task_state.json）。"""
    fac = Factory(mode="done")
    mgr = _mk_manager(tmp_path, fac=fac)
    ws = _mk_ws(tmp_path, mgr)
    path = mgr.get_workspace(ws["id"])["path"]
    assert mgr.snapshot(ws["id"]).get("pending_resume") is None
    _write_pending_state(path)
    pr = mgr.snapshot(ws["id"]).get("pending_resume")
    assert pr and pr["task_text"] == "恢复演示"
    assert [u["unit_id"] for u in pr["units"]] == ["R-1"]


def test_resume_workspace_spawns_engine_resume(tmp_path):
    """工作区级续跑：建 run → 引擎 resume_task → 终态清理。"""
    import time as _t
    fac = Factory(mode="done")
    mgr = _mk_manager(tmp_path, fac=fac)
    ws = _mk_ws(tmp_path, mgr)
    _write_pending_state(mgr.get_workspace(ws["id"])["path"])
    out = mgr.resume_workspace(ws["id"])
    assert out["run_id"]
    deadline = _t.time() + 3
    while _t.time() < deadline and fac.last.resume_calls < 1:
        _t.sleep(0.05)
    assert fac.last.resume_calls >= 1, "必须调用引擎 resume_task"
    deadline = _t.time() + 3
    while _t.time() < deadline and mgr.snapshot(ws["id"])["active_run"]:
        _t.sleep(0.05)
    assert mgr.snapshot(ws["id"])["active_run"] is None, "续跑收口后无活动任务"


def test_abandon_workspace_renames_pending_state(tmp_path):
    """放弃：pending 状态改名留痕，快照不再报挂起。"""
    fac = Factory(mode="done")
    mgr = _mk_manager(tmp_path, fac=fac)
    ws = _mk_ws(tmp_path, mgr)
    path = pathlib.Path(mgr.get_workspace(ws["id"])["path"])
    _write_pending_state(path)
    out = mgr.abandon_workspace(ws["id"])
    assert out["ok"] is True and out["abandoned"] is True
    assert not (path / "task_state.json").exists()
    assert mgr.snapshot(ws["id"]).get("pending_resume") is None


def test_submit_unit_binding_sidecar(tmp_path):
    """碎片会话后半程（2026-09-22）：碎片内提交 → 轮次 unit 标记 + 绑定 sidecar。"""
    import json
    fac = Factory(mode="done")
    mgr = _mk_manager(tmp_path, fac=fac)
    ws = _mk_ws(tmp_path, mgr)
    path = pathlib.Path(mgr.get_workspace(ws["id"])["path"])
    run_id = mgr.submit(ws["id"], "碎片提交", unit="P-a")
    mgr.wait(run_id, timeout=5)
    bind = path / ".wuxing" / "unit-bindings.jsonl"
    rows = [json.loads(x) for x in
            bind.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(rows) == 1
    assert rows[0]["unit_id"] == "P-a" and rows[0]["round"] == 1
    assert rows[0]["conversation"].startswith("conversation-")
    conv = path / ".wuxing" / rows[0]["conversation"]
    last = json.loads(conv.read_text(encoding="utf-8").splitlines()[-1])
    assert last["round"] == 1 and last["unit"] == "P-a"


def test_submit_without_unit_writes_no_binding(tmp_path):
    """普通提交不落绑定 sidecar（空 unit 零副作用）。"""
    fac = Factory(mode="done")
    mgr = _mk_manager(tmp_path, fac=fac)
    ws = _mk_ws(tmp_path, mgr)
    path = pathlib.Path(mgr.get_workspace(ws["id"])["path"])
    run_id = mgr.submit(ws["id"], "普通提交")
    mgr.wait(run_id, timeout=5)
    assert not (path / ".wuxing" / "unit-bindings.jsonl").exists()


def test_confirm_cleanup_preserves_repending_unit(tmp_path):
    """真测 REAL-14：确认调用期间续跑重挂（同 unit_id）→ 新挂起不得被清理抹掉。

    现场：F-T4 复跑续跑后 F-T4-v 重新挂起，但 manager.confirm 的异步清理
    按 unit_id 把这条“同 id 的新挂起”一并移除 → pending 队列为空、任务卡在
    pending（用户再也确认不了）。
    """
    import time as _t

    fac = Factory(mode="pending")
    mgr = _mk_manager(tmp_path, fac=fac)
    ws = _mk_ws(tmp_path, mgr)
    rid = mgr.submit(ws["id"], "确认任务")
    mgr.wait(rid, timeout=5)
    engine = fac.last

    def confirm_with_repend(items, reason="", on_event=None):
        for uid, approve in items:
            if on_event:
                on_event(UnitStarted(uid, "execute"))
                on_event(UnitNeedsConfirm(uid, "execute", "续跑后重新挂起"))
        return _Result(status="pending", report="重挂")

    engine.confirm_units = confirm_with_repend
    mgr.confirm(rid, [("F-1", True)])
    deadline = _t.time() + 3
    while _t.time() < deadline:
        if mgr.snapshot(ws["id"])["pending_confirms"]:
            break
        _t.sleep(0.05)
    assert mgr.snapshot(ws["id"])["pending_confirms"], \
        "续跑重挂的确认条目必须保留（不得被清理逻辑抹掉）"


def test_resume_workspace_synthesizes_terminal_event(tmp_path):
    """W5.1：静默 resume（引擎不发终态事件）→ 壳补发 task_done（UI 收口）。

    现场：resume_workspace 以新 run 承接恢复；引擎 _resume_task_impl 不发
    TaskDone → 壳 deferred 终态槽为空 → 工作区状态仅靠快照，事件流无终态。
    """
    import time as _t
    fac = Factory(mode="done")
    mgr = _mk_manager(tmp_path, fac=fac)
    ws = _mk_ws(tmp_path, mgr)
    _write_pending_state(mgr.get_workspace(ws["id"])["path"])
    sub, _, _ = mgr.hub.subscribe()
    mgr.resume_workspace(ws["id"])
    deadline = _t.time() + 3
    while _t.time() < deadline and mgr.snapshot(ws["id"])["active_run"]:
        _t.sleep(0.05)
    assert mgr.snapshot(ws["id"])["active_run"] is None
    types = []
    while True:
        ev = sub.get(timeout=0.05)
        if ev is None:
            break
        types.append(ev["type"])
    assert "task_done" in types, f"resume 路径必须有终态事件: {types}"


def test_resume_workspace_surfaces_pending_confirms(tmp_path):
    """W5.1：resume 期间引擎补发 UnitNeedsConfirm → 新 run 快照 pending 可见可确认。"""
    import time as _t

    class PendResumeEngine(FakeEngine):
        def resume_task(self, on_event=None):
            self.resume_calls += 1
            if on_event:
                on_event(UnitNeedsConfirm("F-9", "verify", "恢复态待确认",
                                          {"tools": ["bash"], "depends": []}))
                on_event(TaskDone("pending"))
            return _Result(status="pending", report="挂起",
                           units=[_Unit("F-9", "verify", "needs_confirm")])

    def factory(workdir, auto_confirm):
        return PendResumeEngine(workdir, auto_confirm, mode="done")

    mgr = _mk_manager(tmp_path, fac=factory)
    ws = _mk_ws(tmp_path, mgr)
    _write_pending_state(mgr.get_workspace(ws["id"])["path"])
    mgr.resume_workspace(ws["id"])
    deadline = _t.time() + 3
    while _t.time() < deadline and mgr.snapshot(ws["id"])["active_run"]:
        _t.sleep(0.05)
    snap = mgr.snapshot(ws["id"])
    assert snap["pending_confirms"], snap
    assert snap["pending_confirms"][0]["unit_id"] == "F-9"
    assert snap["pending_confirms"][0]["impact"].get("tools") == ["bash"]


# ---- W5.2：工作区级操作互斥（防并发 task_state 覆盖） ----

def test_submit_allowed_while_confirm_worker_runs_per_run_state(tmp_path):
    """G8-M3：确认 worker 与他会话新提交互不冲突（task_state 按 run 隔离）。

    W5.2 旧风险（同工作区 task_state 覆写）已由 run 作用域状态消除；
    同 run 的重复操作仍被 `_begin_op` 拒绝（另有用例）。
    """
    import time as _t

    fac = Factory(mode="pending")
    mgr = _mk_manager(tmp_path, fac=fac)
    ws = _mk_ws(tmp_path, mgr)
    rid = mgr.submit(ws["id"], "确认任务")
    mgr.wait(rid, timeout=5)
    engine = fac.last
    entered = threading.Event()
    gate = threading.Event()

    def blocking_confirm(items, reason="", on_event=None):
        entered.set()
        gate.wait(5)
        return _Result(status="done", report="确认后")

    engine.confirm_units = blocking_confirm
    mgr.confirm(rid, [("F-1", True)])
    assert entered.wait(3), "确认 worker 必须已进入引擎"
    rid2 = mgr.submit(ws["id"], "第二个任务")   # 不同会话 → 允许（各自 run 状态）
    assert rid2 and rid2 != rid
    gate.set()
    deadline = _t.time() + 3
    while _t.time() < deadline and rid2 not in mgr._runs:
        _t.sleep(0.02)
    mgr.wait(rid2, timeout=5)


def test_resume_rejected_while_active(tmp_path):
    """W5.2：活动任务运行中不得对同一工作区发起 resume（防并发覆盖）。"""
    from wuxing.shell.web.manager import BusyError

    fac = Factory(mode="done", auto_release=False)
    mgr = _mk_manager(tmp_path, fac=fac)
    ws = _mk_ws(tmp_path, mgr)
    rid = mgr.submit(ws["id"], "长任务")
    assert fac.last.started.wait(3)
    with pytest.raises(BusyError):
        mgr.resume(rid)
    fac.last.release.set()
    mgr.wait(rid, timeout=5)


def test_command_worker_releases_busy_after_error(tmp_path):
    """W5.2：命令 worker 异常路径也必须释放操作登记（否则工作区永挂 busy）。"""
    import time as _t

    from wuxing.shell.web.manager import BusyError

    fac = Factory(mode="pending")
    mgr = _mk_manager(tmp_path, fac=fac)
    ws = _mk_ws(tmp_path, mgr)
    rid = mgr.submit(ws["id"], "确认任务")
    mgr.wait(rid, timeout=5)

    def boom(items, reason="", on_event=None):
        raise RuntimeError("explode")

    fac.last.confirm_units = boom
    mgr.confirm(rid, [("F-1", True)])
    deadline = _t.time() + 3
    rid2 = None
    while _t.time() < deadline:
        try:
            rid2 = mgr.submit(ws["id"], "后续任务")
            break
        except BusyError:
            _t.sleep(0.05)
    assert rid2, "异常后必须释放操作登记"
    mgr.wait(rid2, timeout=5)


def test_history_concurrent_append_and_read_no_loss(tmp_path):
    """历史加固（P0-1 门禁复跑暴露）：并发追加 + 并发读取不得丢行/半读。

    现场：ci_check 全量负载下 test_shell_api 双工作区并行偶发
    history 为空（IndexError）——追加/读取未串行导致读者可见半写状态。
    """
    from wuxing.shell.web.manager import _Run
    fac = Factory(mode="done")
    mgr = _mk_manager(tmp_path, fac=fac)
    ws = _mk_ws(tmp_path, mgr)
    n_threads, per = 4, 10
    barrier = threading.Barrier(n_threads)

    def writer(k):
        barrier.wait()
        for i in range(per):
            rec = _Run(f"r{k}-{i}", ws["id"], "t")
            rec.status = "done"
            mgr._append_history(rec)

    threads = [threading.Thread(target=writer, args=(k,))
               for k in range(n_threads)]
    for t in threads:
        t.start()
    for _ in range(50):
        mgr.history(ws["id"], limit=None)
    for t in threads:
        t.join()
    rows = mgr.history(ws["id"], limit=None)
    assert len(rows) == n_threads * per, f"并发追加丢行：{len(rows)}"
