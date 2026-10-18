"""TDD：REST + SSE 接线（壳 P1 · B4）——快照-流握手/确认回路/取消驳回。

设计 §4.1/§4.2：REST 命令面（/api/v1）+ SSE 事件流（hello → 重放 → 实时）；
快照含 last_seq（高水位）——客户端以 since 无缝续流；缺口 → resync_required。
"""
import http.client
import json
import threading
import time

from wuxing.shell.web.hub import CLOSED, EventHub


# ---- 假引擎（同 B3 约定：事件对象名与 wuxing.events 对齐） ----
class UnitStarted:
    def __init__(self, unit_id, domain_id):
        self.unit_id, self.domain_id = unit_id, domain_id


class UnitDone:
    def __init__(self, unit_id, domain_id, status):
        self.unit_id, self.domain_id, self.status = unit_id, domain_id, status


class UnitNeedsConfirm:
    def __init__(self, unit_id, domain_id, reason=""):
        self.unit_id, self.domain_id, self.reason = unit_id, domain_id, reason


class TaskDone:
    def __init__(self, status):
        self.status = status


class _Result:
    def __init__(self, status="done", report="报告", artifacts=None,
                 metrics=None):
        self.status = status
        self.report = report
        self.artifacts = artifacts or []
        self.metrics = metrics or {}


class FakeEngine:
    def __init__(self, workdir, auto_confirm=False, mode="done"):
        self.workdir = workdir
        self.auto_confirm = auto_confirm
        self.mode = mode
        self.started = threading.Event()
        self.release = threading.Event()
        self.release.set()
        self.confirm_calls = []
        self.cancelled = False
        self.resumed = 0

    def start_session(self, conversation_path=None):
        """修复①（2026-09-20）：manager 经引擎公开 API 建会话——测试桩用真实实现。"""
        from wuxing.conversation import ConversationState
        from wuxing.session_api import ConversationSession
        return ConversationSession(self, ConversationState(conversation_path))

    def run_task(self, text, on_event=None, references=None, conversation=None,
                 overrides=None):
        if on_event:
            on_event(UnitStarted("F-1", "execute"))
        self.started.set()
        self.release.wait(5)
        if self.mode == "pending":
            if on_event:
                on_event(UnitNeedsConfirm("F-1", "execute", "窗口切换待确认"))
            return _Result(status="pending", report="待确认")
        if on_event:
            on_event(UnitDone("F-1", "execute", "ok"))
            on_event(TaskDone("done"))
        if self.mode == "slow_return":
            time.sleep(0.4)   # 模拟引擎返回前的收尾（结果组装）——事件抢先的竞态窗口
        return _Result(status="done")

    def confirm_units(self, items, reason="", on_event=None):
        self.confirm_calls.append((list(items), reason))
        for uid, approve in items:
            if on_event:
                on_event(UnitStarted(uid, "execute"))
                on_event(UnitDone(uid, "execute", "ok" if approve else "rejected"))
        if on_event:
            on_event(TaskDone("done"))
        return _Result(status="done")

    def resume_task(self, on_event=None):
        self.resumed += 1
        return _Result(status="done")

    def cancel_task(self):
        self.cancelled = True
        return True

    def list_skills(self):
        return [{"name": "demo-skill", "description": "演示技能",
                 "level": "project"}]


class Factory:
    def __init__(self, mode="done", auto_release=True):
        self.mode = mode
        self.auto_release = auto_release
        self.last = None
        self.engines = {}

    def __call__(self, workdir, auto_confirm):
        eng = FakeEngine(workdir, auto_confirm, mode=self.mode)
        if not self.auto_release:
            eng.release.clear()   # 手工释放——用于并行/挂起场景
        self.last = eng
        self.engines[str(workdir)] = eng
        return eng


def _mk_server(tmp_path, mode="done", hub=None, max_concurrent=2,
               auto_release=True):
    from wuxing.shell.web.api import register_api
    from wuxing.shell.web.manager import EngineManager
    from wuxing.shell.web.server import ShellServer
    hub = hub or EventHub()
    fac = Factory(mode=mode, auto_release=auto_release)
    mgr = EngineManager(hub=hub, engine_factory=fac,
                        state_path=tmp_path / "ws.json",
                        max_concurrent=max_concurrent)
    srv = ShellServer(port=0, hub=hub)
    register_api(srv, mgr)
    port = srv.start()
    return srv, port, mgr, fac


def _request(port, method, path, body=None, headers=None):
    c = http.client.HTTPConnection("127.0.0.60", port, timeout=5)
    c.request(method, path, body=body, headers=headers or {})
    r = c.getresponse()
    data = r.read()
    status = r.status
    c.close()
    return status, data


def _post_json(port, path, payload):
    return _request(port, "POST", path, body=json.dumps(payload),
                    headers={"X-Wuxing": "1",
                             "Content-Type": "application/json"})


def _open_sse(port, path):
    c = http.client.HTTPConnection("127.0.0.60", port, timeout=8)
    c.request("GET", path)
    return c, c.getresponse()


def _read_sse(resp, count, timeout=5):
    events, deadline = [], time.time() + timeout
    cur = {}
    while len(events) < count and time.time() < deadline:
        try:
            raw = resp.fp.readline()
        except (TimeoutError, OSError):
            break
        if not raw:
            break
        line = raw.decode("utf-8", "replace").strip()
        if line.startswith("event:"):
            cur = {"event": line.split(":", 1)[1].strip()}
        elif line.startswith("data:"):
            cur["data"] = json.loads(line.split(":", 1)[1].strip())
        elif not line and cur:
            events.append(cur)
            cur = {}
    return events


def test_workspace_endpoints_crud(tmp_path):
    srv, port, _mgr, _fac = _mk_server(tmp_path)
    wd = tmp_path / "proj"
    wd.mkdir()
    try:
        status, data = _post_json(port, "/api/v1/workspaces",
                                  {"path": str(wd)})
        assert status == 200, data
        ws = json.loads(data)
        assert ws["name"] == "proj"
        status, data = _request(port, "GET", "/api/v1/workspaces")
        assert status == 200 and json.loads(data)["workspaces"][0]["id"] == ws["id"]
        status, data = _request(port, "DELETE",
                                f"/api/v1/workspaces/{ws['id']}",
                                headers={"X-Wuxing": "1"})
        assert status == 200
        status, _data = _request(port, "GET", "/api/v1/workspaces")
        assert json.loads(_data)["workspaces"] == []
    finally:
        srv.stop()


def test_submit_override_validation(tmp_path):
    """未知 override → 422；no_map → 202（透传由 manager 测试覆盖）。"""
    srv, port, _mgr, _fac = _mk_server(tmp_path)
    wd = tmp_path / "proj"
    wd.mkdir()
    try:
        _s, data = _post_json(port, "/api/v1/workspaces", {"path": str(wd)})
        ws = json.loads(data)
        status, _d = _post_json(port, f"/api/v1/workspaces/{ws['id']}/tasks",
                                {"text": "x", "override": "nope"})
        assert status == 422
        status, _d = _post_json(port, f"/api/v1/workspaces/{ws['id']}/tasks",
                                {"text": "x", "override": "no_map"})
        assert status == 202
    finally:
        srv.stop()


def test_task_history_endpoint(tmp_path):
    """任务历史端点（UI 重构 · 阶段 2.4）：壳侧日志，新→旧。"""
    srv, port, mgr, _fac = _mk_server(tmp_path)
    wd = tmp_path / "proj"
    wd.mkdir()
    try:
        _s, data = _post_json(port, "/api/v1/workspaces", {"path": str(wd)})
        ws = json.loads(data)
        _s, data = _post_json(port, f"/api/v1/workspaces/{ws['id']}/tasks",
                              {"text": "历史任务"})
        run_id = json.loads(data)["run_id"]
        mgr.wait(run_id, timeout=5)
        status, data = _request(
            port, "GET", f"/api/v1/workspaces/{ws['id']}/tasks/history")
        assert status == 200, data
        hist = json.loads(data)["history"]
        assert hist and hist[0]["run_id"] == run_id
        assert hist[0]["task_text"] == "历史任务"
        assert hist[0]["status"] == "done"
    finally:
        srv.stop()


def test_fs_list_endpoint(tmp_path):
    """目录浏览端点（新建工作区·浏览本地目录用）：只列子目录，不列文件。"""
    srv, port, _mgr, _fac = _mk_server(tmp_path)
    root = tmp_path / "dirs"
    (root / "sub1").mkdir(parents=True)
    (root / "sub2").mkdir()
    (root / ".hidden").mkdir()
    (root / "file.txt").write_text("x", encoding="utf-8")
    try:
        status, data = _request(port, "GET", f"/api/v1/fs/list?path={root}")
        assert status == 200, data
        out = json.loads(data)
        names = [d["name"] for d in out["dirs"]]
        assert names == ["sub1", "sub2"], names
        assert "file.txt" not in names
        assert out["parent"] == str(tmp_path)
        status, _d = _request(
            port, "GET", f"/api/v1/fs/list?path={tmp_path / 'nope'}")
        assert status == 404
    finally:
        srv.stop()


def test_open_workspace_with_custom_name(tmp_path):
    srv, port, _mgr, _fac = _mk_server(tmp_path)
    wd = tmp_path / "proj"
    wd.mkdir()
    try:
        status, data = _post_json(port, "/api/v1/workspaces",
                                  {"path": str(wd), "name": "自定义名"})
        assert status == 200, data
        assert json.loads(data)["name"] == "自定义名"
    finally:
        srv.stop()


def test_submit_snapshot_and_busy_409(tmp_path):
    srv, port, _mgr, _fac = _mk_server(tmp_path)
    wd = tmp_path / "proj"
    wd.mkdir()
    try:
        _status, data = _post_json(port, "/api/v1/workspaces", {"path": str(wd)})
        ws_id = json.loads(data)["id"]
        status, data = _post_json(port, f"/api/v1/workspaces/{ws_id}/tasks",
                                  {"text": "任务"})
        assert status == 202, data
        run_id = json.loads(data)["run_id"]
        deadline = time.time() + 5
        snap = None
        while time.time() < deadline:
            _s, raw = _request(port, "GET",
                               f"/api/v1/workspaces/{ws_id}/snapshot")
            snap = json.loads(raw)
            if snap["active_run"] is None and snap["result"]:
                break
            time.sleep(0.05)
        assert snap["result"]["status"] == "done", snap
        assert "last_seq" in snap, "快照必须含高水位 last_seq"
        status, data = _request(
            port, "POST", f"/api/v1/workspaces/{ws_id}/tasks/{run_id}/cancel",
            headers={"X-Wuxing": "1"})
        assert status == 200
    finally:
        srv.stop()


def test_confirm_endpoint(tmp_path):
    srv, port, mgr, fac = _mk_server(tmp_path, mode="pending")
    wd = tmp_path / "proj"
    wd.mkdir()
    try:
        _s, data = _post_json(port, "/api/v1/workspaces", {"path": str(wd)})
        ws_id = json.loads(data)["id"]
        _s, data = _post_json(port, f"/api/v1/workspaces/{ws_id}/tasks",
                              {"text": "任务"})
        run_id = json.loads(data)["run_id"]
        mgr.wait(run_id, timeout=5)
        _s, raw = _request(port, "GET", f"/api/v1/workspaces/{ws_id}/snapshot")
        pending = json.loads(raw)["pending_confirms"]
        assert pending and pending[0]["unit_id"] == "F-1"
        status, _d = _post_json(
            port,
            f"/api/v1/workspaces/{ws_id}/tasks/{run_id}/confirm",
            {"items": [["F-1", True]], "reason": "批准"})
        assert status == 200
        # 确认走工作线程（设计 §4.4）——轮询等待引擎调用与挂起清理
        deadline = time.time() + 3
        while time.time() < deadline and not fac.last.confirm_calls:
            time.sleep(0.05)
        assert fac.last.confirm_calls == [([("F-1", True)], "批准")]
        deadline = time.time() + 3
        while time.time() < deadline:
            _s, raw = _request(port, "GET",
                               f"/api/v1/workspaces/{ws_id}/snapshot")
            if json.loads(raw)["pending_confirms"] == []:
                break
            time.sleep(0.05)
        _s, raw = _request(port, "GET", f"/api/v1/workspaces/{ws_id}/snapshot")
        assert json.loads(raw)["pending_confirms"] == []
    finally:
        srv.stop()


def test_terminal_event_arrives_after_result_visible(tmp_path):
    """事件契约（审查 I4）：task_done 到达时，快照必须已含 result。

    根因回归：引擎先发 task_done、后返回结果——若事件即时转发，客户端在此期间
    拉快照会拿到「有 task_text 无 result」的中间态（指标/产物数/重渲染丢失）。
    修复：终态事件缓发（result 先落库，再发事件）。
    """
    hub = EventHub()
    srv, port, mgr, _fac = _mk_server(tmp_path, mode="slow_return", hub=hub)
    wd = tmp_path / "proj"
    wd.mkdir()
    try:
        _s, d = _post_json(port, "/api/v1/workspaces", {"path": str(wd)})
        ws_id = json.loads(d)["id"]
        sub, _replay, _gap = hub.subscribe()
        _post_json(port, f"/api/v1/workspaces/{ws_id}/tasks", {"text": "竞态验证"})
        got = None
        deadline = time.time() + 5
        while time.time() < deadline:
            ev = sub.get(timeout=0.5)
            if ev is None or ev is CLOSED:
                continue
            if ev.get("type") == "task_done":
                got = ev
                break
        assert got is not None, "未收到 task_done"
        snap = mgr.snapshot(ws_id)
        assert snap["result"] is not None, \
            "task_done 到达时快照必须已含 result（result 先落库再发事件）"
        assert snap["result"]["status"] == "done"
    finally:
        srv.stop()


def test_sse_delivers_deferred_terminal_event(tmp_path):
    """SSE 必须送达缓发的终态事件（I4 服务端修复的回归防线）。"""
    hub = EventHub()
    srv, port, _mgr, _fac = _mk_server(tmp_path, mode="slow_return", hub=hub)
    wd = tmp_path / "proj"
    wd.mkdir()
    try:
        _s, d = _post_json(port, "/api/v1/workspaces", {"path": str(wd)})
        ws_id = json.loads(d)["id"]
        conn, resp = _open_sse(port, "/api/v1/events?since=0")
        assert resp.status == 200
        hello = _read_sse(resp, 1, timeout=5)
        assert hello and hello[0]["event"] == "hello"
        _post_json(port, f"/api/v1/workspaces/{ws_id}/tasks", {"text": "SSE 终态"})
        got = _read_sse(resp, 4, timeout=8)
        types = [e["data"].get("type") for e in got]
        assert "task_done" in types, types
        conn.close()
    finally:
        srv.stop()


def test_sse_handshake_replay_and_stream(tmp_path):
    hub = EventHub()
    srv, port, _mgr, _fac = _mk_server(tmp_path, hub=hub)
    try:
        hub.emit("custom_a", workspace_id="w1", data={"i": 1})
        hub.emit("custom_b", workspace_id="w1", data={"i": 2})
        conn, resp = _open_sse(port, "/api/v1/events?since=0")
        assert resp.status == 200
        assert "text/event-stream" in resp.headers.get("Content-Type", "")
        events = _read_sse(resp, 3)
        assert events[0]["event"] == "hello", events
        assert events[0]["data"]["epoch"] == hub.epoch
        assert events[0]["data"]["gap"] is False
        # 常规事件 = 未命名 message 帧（type 在 data 内）——新增事件类型无需前端白名单
        assert [e.get("event") for e in events[1:]] == [None, None]
        assert [e["data"]["type"] for e in events[1:]] == ["custom_a", "custom_b"]
        assert [e["data"]["seq"] for e in events[1:]] == [1, 2]
        # 实时追加（订阅已建立 → 实时扇出）
        hub.emit("custom_c", workspace_id="w1", data={"i": 3})
        more = _read_sse(resp, 1)
        assert more and more[0].get("event") is None
        assert more[0]["data"]["type"] == "custom_c"
        conn.close()
    finally:
        srv.stop()


def test_all_registered_api_routes_are_versioned(tmp_path):
    """版本化收口（T6.1）：除基础端点 /health 外，全部路由挂在 /api/v1 前缀下。"""
    from wuxing.shell.web.version import API_PREFIX
    srv, _port, _mgr, _fac = _mk_server(tmp_path)
    try:
        patterns = [pat.pattern for _m, pat, _fn in srv.routes]
        assert patterns[0] == r"^/health$", patterns[0]   # 基础端点例外（非 API 面）
        for pat in patterns[1:]:
            assert pat.lstrip("^").startswith(API_PREFIX), pat
    finally:
        srv.stop()


def test_two_workspaces_parallel_tasks_full_loop(tmp_path):
    """集成验收（壳设计 P1 门 1）：双工作区并行 2 任务（mock）全链路。

    并行非排队：两引擎同时处于 running；各自释放后独立完成 + 历史归档。
    """
    srv, port, _mgr, fac = _mk_server(tmp_path, auto_release=False)
    wd1 = tmp_path / "proj-a"
    wd2 = tmp_path / "proj-b"
    wd1.mkdir()
    wd2.mkdir()
    try:
        _s, d1 = _post_json(port, "/api/v1/workspaces", {"path": str(wd1)})
        ws1 = json.loads(d1)["id"]
        _s, d2 = _post_json(port, "/api/v1/workspaces", {"path": str(wd2)})
        ws2 = json.loads(d2)["id"]
        _s, r1 = _post_json(port, f"/api/v1/workspaces/{ws1}/tasks",
                            {"text": "任务一"})
        _s, r2 = _post_json(port, f"/api/v1/workspaces/{ws2}/tasks",
                            {"text": "任务二"})
        run1 = json.loads(r1)["run_id"]
        run2 = json.loads(r2)["run_id"]
        # 并行证明：两引擎同时启动（未释放）
        assert fac.engines[str(wd1)].started.wait(5)
        assert fac.engines[str(wd2)].started.wait(5)
        for wid in (ws1, ws2):
            _s, snap = _request(port, "GET",
                                f"/api/v1/workspaces/{wid}/snapshot")
            active = json.loads(snap)["active_run"]
            assert active and active["status"] == "running", snap
        # 各自释放 → 独立完成 + 历史可查
        fac.engines[str(wd1)].release.set()
        fac.engines[str(wd2)].release.set()
        for wid, rid, task in ((ws1, run1, "任务一"), (ws2, run2, "任务二")):
            deadline = time.time() + 5
            result = None
            while time.time() < deadline:
                _s, snap = _request(port, "GET",
                                    f"/api/v1/workspaces/{wid}/snapshot")
                s = json.loads(snap)
                if not s["active_run"]:
                    result = s.get("result")
                    break
                time.sleep(0.05)
            assert result and result["status"] == "done", (wid, result)
            _s, hist = _request(port, "GET",
                                f"/api/v1/workspaces/{wid}/tasks/history")
            row = json.loads(hist)["history"][0]
            assert row["run_id"] == rid and row["task_text"] == task
            assert row["status"] == "done"
    finally:
        srv.stop()


def test_history_survives_transient_append_lock(tmp_path, monkeypatch):
    """历史追加遇 Windows 瞬态占用（PermissionError）应重试——不得静默丢行。"""
    import pathlib

    srv, port, _mgr, _fac = _mk_server(tmp_path)  # auto_release=True：提交即完成
    try:
        real_open = pathlib.Path.open
        calls = {"n": 0}

        def flaky_open(self, *args, **kwargs):
            if self.name == "tasks.jsonl" and args and args[0] == "a":
                calls["n"] += 1
                if calls["n"] == 1:
                    raise PermissionError(5, "拒绝访问")
            return real_open(self, *args, **kwargs)

        monkeypatch.setattr(pathlib.Path, "open", flaky_open)
        _s, d = _post_json(port, "/api/v1/workspaces", {"path": str(tmp_path)})
        ws = json.loads(d)["id"]
        _s, r = _post_json(port, f"/api/v1/workspaces/{ws}/tasks", {"text": "重试"})
        run_id = json.loads(r)["run_id"]
        deadline = time.time() + 5
        while time.time() < deadline:
            _s, snap = _request(port, "GET", f"/api/v1/workspaces/{ws}/snapshot")
            if not json.loads(snap)["active_run"]:
                break
            time.sleep(0.05)
        _s, hist = _request(port, "GET", f"/api/v1/workspaces/{ws}/tasks/history")
        rows = json.loads(hist)["history"]
        assert rows and rows[0]["run_id"] == run_id, f"history={rows} calls={calls}"
        assert calls["n"] >= 1
    finally:
        srv.stop()


def test_history_read_survives_transient_lock(tmp_path, monkeypatch):
    """历史读取遇瞬态占用应重试——不得静默返回空（全量套件 flake 回归守卫）。"""
    import pathlib

    srv, port, _mgr, _fac = _mk_server(tmp_path)
    try:
        _s, d = _post_json(port, "/api/v1/workspaces", {"path": str(tmp_path)})
        ws = json.loads(d)["id"]
        _s, r = _post_json(port, f"/api/v1/workspaces/{ws}/tasks", {"text": "读重试"})
        run_id = json.loads(r)["run_id"]
        deadline = time.time() + 5
        while time.time() < deadline:
            _s, snap = _request(port, "GET", f"/api/v1/workspaces/{ws}/snapshot")
            if not json.loads(snap)["active_run"]:
                break
            time.sleep(0.05)
        real_read = pathlib.Path.read_text
        calls = {"n": 0}

        def flaky_read(self, *args, **kwargs):
            if self.name == "tasks.jsonl":
                calls["n"] += 1
                if calls["n"] == 1:
                    raise PermissionError(5, "拒绝访问")
            return real_read(self, *args, **kwargs)

        monkeypatch.setattr(pathlib.Path, "read_text", flaky_read)
        _s, hist = _request(port, "GET", f"/api/v1/workspaces/{ws}/tasks/history")
        rows = json.loads(hist)["history"]
        assert rows and rows[0]["run_id"] == run_id, f"history={rows} calls={calls}"
        assert calls["n"] >= 1
    finally:
        srv.stop()


def test_sse_resync_required_on_gap(tmp_path):
    hub = EventHub(ring_size=2)
    srv, port, _mgr, _fac = _mk_server(tmp_path, hub=hub)
    try:
        for i in range(5):
            hub.emit("e", data={"i": i})
        conn, resp = _open_sse(port, "/api/v1/events?since=0")
        events = _read_sse(resp, 2)
        assert events[0]["event"] == "hello" and events[0]["data"]["gap"] is True
        assert events[1]["event"] == "resync_required"
        conn.close()
    finally:
        srv.stop()


def test_artifact_endpoint_containment(tmp_path):
    srv, port, _mgr, _fac = _mk_server(tmp_path)
    wd = tmp_path / "proj"
    wd.mkdir()
    (wd / "out.md").write_text("# 结果", encoding="utf-8")
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET", encoding="utf-8")
    try:
        _s, data = _post_json(port, "/api/v1/workspaces", {"path": str(wd)})
        ws_id = json.loads(data)["id"]
        status, body = _request(
            port, "GET", f"/api/v1/workspaces/{ws_id}/artifacts/out.md")
        assert status == 200 and "结果" in body.decode("utf-8")
        status, body = _request(
            port, "GET",
            f"/api/v1/workspaces/{ws_id}/artifacts/..%2Fsecret.txt")
        assert status in (403, 404) and b"TOP-SECRET" not in body
    finally:
        srv.stop()


def test_sessions_endpoints(tmp_path):
    srv, port, _mgr, _fac = _mk_server(tmp_path)
    wd = tmp_path / "proj"
    (wd / ".wuxing").mkdir(parents=True)
    (wd / ".wuxing" / "conversation.jsonl").write_text(
        json.dumps({"round": 1, "user_text": "你好"}) + "\n",
        encoding="utf-8")
    (wd / ".wuxing" / "provenance.jsonl").write_text("{}\n", encoding="utf-8")
    # 2026-09-27 审查：tickets.jsonl 非会话——不得出现在会话列表（幽灵会话）
    (wd / ".wuxing" / "tickets.jsonl").write_text("{}\n", encoding="utf-8")
    try:
        _s, data = _post_json(port, "/api/v1/workspaces", {"path": str(wd)})
        ws_id = json.loads(data)["id"]
        status, body = _request(
            port, "GET", f"/api/v1/workspaces/{ws_id}/sessions")
        names = [s["name"] for s in json.loads(body)["sessions"]]
        assert names == ["conversation.jsonl"], \
            "会话列表只含会话文件（内部观测/票据文件排除）"
        status, body = _request(
            port, "GET",
            f"/api/v1/workspaces/{ws_id}/sessions/conversation.jsonl")
        assert status == 200
        rows = json.loads(body)["rows"]
        assert rows[0]["user_text"] == "你好"
    finally:
        srv.stop()


def test_skills_and_rollback_and_task_archive(tmp_path):
    """阶段 2 验收整改：技能清单端点 / 回滚端点 / 任务归档隐藏。"""
    srv, port, mgr, _fac = _mk_server(tmp_path)
    wd = tmp_path / "proj"
    wd.mkdir()
    try:
        _s, data = _post_json(port, "/api/v1/workspaces", {"path": str(wd)})
        ws = json.loads(data)
        # 技能清单
        status, data = _request(port, "GET",
                                f"/api/v1/workspaces/{ws['id']}/skills")
        assert status == 200
        assert json.loads(data)["skills"][0]["name"] == "demo-skill"
        # 跑一个任务 → 回滚
        _s, data = _post_json(port, f"/api/v1/workspaces/{ws['id']}/tasks",
                              {"text": "回滚端点任务"})
        run_id = json.loads(data)["run_id"]
        mgr.wait(run_id, timeout=5)
        status, data = _post_json(
            port, f"/api/v1/workspaces/{ws['id']}/tasks/{run_id}/rollback",
            {"delete_artifacts": False})
        assert status == 200, data
        assert json.loads(data)["ok"] is True
        _s, raw = _request(port, "GET",
                           f"/api/v1/workspaces/{ws['id']}/tasks/history")
        assert json.loads(raw)["history"][0]["status"] == "rolled_back"
        # 任务归档 → 历史隐藏
        status, data = _post_json(
            port, f"/api/v1/workspaces/{ws['id']}/tasks/{run_id}/archive",
            {"state": "trashed"})
        assert status == 200 and json.loads(data)["kind"] == "task"
        _s, raw = _request(port, "GET",
                           f"/api/v1/workspaces/{ws['id']}/tasks/history")
        assert json.loads(raw)["history"] == []
        # 回收站彻底删除 → 历史行移除
        eid = json.loads(data)["id"]
        status, _d = _request(port, "DELETE",
                              f"/api/v1/recycle/{eid}?purge=true",
                              headers={"X-Wuxing": "1"})
        assert status == 200
        _s, raw = _request(port, "GET",
                           f"/api/v1/workspaces/{ws['id']}/tasks/history")
        assert json.loads(raw)["history"] == []
    finally:
        srv.stop()


def test_config_endpoints(tmp_path, monkeypatch):
    """设置中心端点（阶段 3）：schema / 工作区生效值+sources / 写入（scope 分派 + 引擎重建）。"""
    import wuxing.config_contract as cc
    monkeypatch.setattr(cc, "user_config_path", lambda: tmp_path / "user.jsonc")
    srv, port, _mgr, _fac = _mk_server(tmp_path)
    wd = tmp_path / "proj"
    wd.mkdir()
    try:
        _s, data = _post_json(port, "/api/v1/workspaces", {"path": str(wd)})
        ws = json.loads(data)
        # schema
        status, data = _request(port, "GET", "/api/v1/config/schema")
        assert status == 200
        fields = json.loads(data)["fields"]
        assert any(f["name"] == "max_loop_rounds" and f["scope"] for f in fields)
        # 生效值 + 来源
        status, data = _request(port, "GET",
                                f"/api/v1/workspaces/{ws['id']}/config")
        assert status == 200
        eff = json.loads(data)
        assert eff["sources"]["max_loop_rounds"] == "default"
        # 写入工作区级
        status, data = _request(
            port, "PUT",
            f"/api/v1/config?scope=workspace&ws={ws['id']}",
            body=json.dumps({"values": {"max_loop_rounds": 3}}),
            headers={"X-Wuxing": "1", "Content-Type": "application/json"})
        assert status == 200, data
        assert json.loads(data)["ok"] is True
        _s, data = _request(port, "GET",
                            f"/api/v1/workspaces/{ws['id']}/config")
        eff2 = json.loads(data)
        assert eff2["values"]["max_loop_rounds"] == 3
        assert eff2["sources"]["max_loop_rounds"] == "workspace"
        # 非法值 → 422
        status, _d = _request(
            port, "PUT", f"/api/v1/config?scope=workspace&ws={ws['id']}",
            body=json.dumps({"values": {"max_loop_rounds": "x"}}),
            headers={"X-Wuxing": "1", "Content-Type": "application/json"})
        assert status == 422
    finally:
        srv.stop()


def test_workspace_settings_and_maintenance(tmp_path, monkeypatch):
    """工作区设置（auto_confirm）+ 数据与维护（概览/清理）。"""
    import wuxing.config_contract as cc
    monkeypatch.setattr(cc, "user_config_path", lambda: tmp_path / "user.jsonc")
    srv, port, _mgr, _fac = _mk_server(tmp_path)
    wd = tmp_path / "proj"
    wd.mkdir()
    try:
        _s, data = _post_json(port, "/api/v1/workspaces", {"path": str(wd)})
        ws = json.loads(data)
        # auto_confirm 开关
        status, data = _request(
            port, "PUT", f"/api/v1/workspaces/{ws['id']}/settings",
            body=json.dumps({"auto_confirm": True}),
            headers={"X-Wuxing": "1", "Content-Type": "application/json"})
        assert status == 200, data
        assert json.loads(data)["auto_confirm"] is True
        # 维护概览
        (wd / "reply_cache.json").write_text("{}", encoding="utf-8")
        status, data = _request(
            port, "GET", f"/api/v1/maintenance?ws={ws['id']}")
        assert status == 200
        info = json.loads(data)
        assert any(c["name"] == "reply_cache.json" and c["size"] > 0
                   for c in info["workspace"]["caches"])
        # 清理工作区缓存
        status, data = _request(
            port, "POST", "/api/v1/maintenance/clean",
            body=json.dumps({"target": "workspace_cache", "ws": ws["id"]}),
            headers={"X-Wuxing": "1", "Content-Type": "application/json"})
        assert status == 200
        assert "reply_cache.json" in json.loads(data)["removed"]
        assert not (wd / "reply_cache.json").exists()
    finally:
        srv.stop()


# ---- 工作区文件夹端点（验收迭代 3 · 4b） ----

def _mut(port, method, path, payload=None):
    return _request(port, method, path,
                    body=json.dumps(payload) if payload is not None else None,
                    headers={"X-Wuxing": "1", "Content-Type": "application/json"})


def test_folders_endpoints(tmp_path):
    srv, port, _mgr, _fac = _mk_server(tmp_path)
    wd = tmp_path / "proj"
    wd.mkdir()
    try:
        _s, data = _post_json(port, "/api/v1/workspaces", {"path": str(wd)})
        ws = json.loads(data)
        # 创建文件夹
        status, data = _mut(port, "POST", "/api/v1/folders", {"name": "前端"})
        assert status == 200, data
        folder = json.loads(data)
        assert folder["name"] == "前端" and folder["id"]
        # 列表携带 folders
        status, data = _request(port, "GET", "/api/v1/workspaces")
        payload = json.loads(data)
        assert payload["folders"][0]["id"] == folder["id"]
        # 归入
        status, data = _mut(port, "PUT", f"/api/v1/workspaces/{ws['id']}/folder",
                            {"folder": folder["id"]})
        assert status == 200, data
        assert json.loads(data)["workspace"]["folder"] == folder["id"]
        # 重命名 + 折叠
        status, data = _mut(port, "PATCH", f"/api/v1/folders/{folder['id']}",
                            {"name": "组B", "collapsed": True})
        assert status == 200, data
        renamed = json.loads(data)
        assert renamed["name"] == "组B" and renamed["collapsed"] is True
        # 未知文件夹 → 404
        status, _d = _mut(port, "PUT", f"/api/v1/workspaces/{ws['id']}/folder",
                          {"folder": "nope"})
        assert status == 404
        # 删除 → 工作区回到未分组
        status, data = _mut(port, "DELETE", f"/api/v1/folders/{folder['id']}")
        assert status == 200, data
        status, data = _request(port, "GET", "/api/v1/workspaces")
        payload = json.loads(data)
        assert payload["folders"] == []
        assert payload["workspaces"][0]["folder"] is None
        # 非变更方法缺 X-Wuxing → 403
        status, _d = _request(port, "POST", "/api/v1/folders",
                              body=json.dumps({"name": "x"}),
                              headers={"Content-Type": "application/json"})
        assert status == 403
    finally:
        srv.stop()


def test_global_config_endpoint_without_workspace(tmp_path, monkeypatch):
    """无工作区时设置中心读用户级配置（GET /api/v1/config）。"""
    import wuxing.config_contract as cc
    user_cfg = tmp_path / "user.jsonc"
    user_cfg.write_text('{"max_loop_rounds": 7}', encoding="utf-8")
    monkeypatch.setattr(cc, "user_config_path", lambda: user_cfg)
    srv, port, _mgr, _fac = _mk_server(tmp_path)
    try:
        status, data = _request(port, "GET", "/api/v1/config")
        assert status == 200, data
        payload = json.loads(data)
        assert payload["values"]["max_loop_rounds"] == 7
        assert payload["sources"]["max_loop_rounds"] == "user"
    finally:
        srv.stop()


def test_config_write_replace_keys(tmp_path, monkeypatch):
    """PUT /api/v1/config 支持 replace：字典型字段整体替换（删除条目）。"""
    import wuxing.config_contract as cc
    monkeypatch.setattr(cc, "user_config_path", lambda: tmp_path / "user.jsonc")
    srv, port, _mgr, _fac = _mk_server(tmp_path)
    try:
        _mut(port, "PUT", "/api/v1/config?scope=user",
             {"values": {"context_tool_limits": {"read_file": 1, "bash": 2}}})
        _mut(port, "PUT", "/api/v1/config?scope=user",
             {"values": {"context_tool_limits": {"bash": 5}}})
        _s, data = _request(port, "GET", "/api/v1/config")
        assert json.loads(data)["values"]["context_tool_limits"] == {"read_file": 1, "bash": 5}
        _mut(port, "PUT", "/api/v1/config?scope=user",
             {"values": {"context_tool_limits": {"bash": 5}},
              "replace": ["context_tool_limits"]})
        _s, data = _request(port, "GET", "/api/v1/config")
        assert json.loads(data)["values"]["context_tool_limits"] == {"bash": 5}
    finally:
        srv.stop()


def test_submit_carries_unit_binding(tmp_path):
    """碎片会话后半程（2026-09-22）：POST /tasks 携带 unit → 响应回显 + 绑定 sidecar。"""
    srv, port, _mgr, _fac = _mk_server(tmp_path)
    wd = tmp_path / "proj"
    wd.mkdir()
    try:
        _status, data = _post_json(port, "/api/v1/workspaces", {"path": str(wd)})
        ws_id = json.loads(data)["id"]
        status, data = _post_json(port, f"/api/v1/workspaces/{ws_id}/tasks",
                                  {"text": "碎片提交", "unit": "P-a"})
        assert status == 202, data
        payload = json.loads(data)
        assert payload["unit"] == "P-a"
        run_id = payload["run_id"]
        deadline = time.time() + 5
        while time.time() < deadline:
            _s, raw = _request(port, "GET", f"/api/v1/workspaces/{ws_id}/snapshot")
            if json.loads(raw)["active_run"] is None:
                break
            time.sleep(0.05)
        bind = wd / ".wuxing" / "unit-bindings.jsonl"
        rows = [json.loads(x) for x in
                bind.read_text(encoding="utf-8").splitlines() if x.strip()]
        assert rows and rows[0]["unit_id"] == "P-a" and rows[0]["round"] == 1
        # 普通提交响应恒有 unit 键（空串——DTO 对拍口径）
        s2, data2 = _post_json(port, f"/api/v1/workspaces/{ws_id}/tasks",
                               {"text": "普通提交"})
        assert s2 == 202 and json.loads(data2)["unit"] == ""
        _ = run_id
    finally:
        srv.stop()
