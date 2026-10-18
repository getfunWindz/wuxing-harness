"""TDD（双模式批 1 · Task 5）：会话模式端点（GET/PUT + 空白校验）。

接口（计划 Task 5 写死）：
- GET  /api/v1/workspaces/{ws}/session-modes?session=<name>
  → {mode, variant, source, editable, picker_enabled, default_mode}
- PUT  同路径 body {mode, variant} → 200 更新后 DTO；
  非空白会话 422（error.code="session/not-blank"）；未知值/未知键 422。
"""
import http.client
import json

from wuxing.shell.web.hub import EventHub


def _mk_server(tmp_path):
    from wuxing.shell.web.api import register_api
    from wuxing.shell.web.manager import EngineManager
    from wuxing.shell.web.server import ShellServer
    hub = EventHub()
    mgr = EngineManager(hub=hub, state_path=tmp_path / "ws.json")
    srv = ShellServer(port=0, hub=hub)
    register_api(srv, mgr)
    port = srv.start()
    return srv, port, mgr


def _request(port, method, path, body=None):
    c = http.client.HTTPConnection("127.0.0.60", port, timeout=10)
    headers = {}
    if method != "GET":
        headers["X-Wuxing"] = "1"
        headers["Content-Type"] = "application/json"
    c.request(method, path,
              body=json.dumps(body) if body is not None else None,
              headers=headers)
    r = c.getresponse()
    data = r.read()
    status = r.status
    c.close()
    return status, data


def _open(tmp_path, mgr, name="proj"):
    wd = tmp_path / name
    wd.mkdir()
    (wd / ".wuxing").mkdir()
    return mgr.open_workspace(str(wd)), wd


def test_session_modes_get_default_and_put_roundtrip(tmp_path):
    srv, port, mgr = _mk_server(tmp_path)
    ws, wd = _open(tmp_path, mgr)
    base = f"/api/v1/workspaces/{ws['id']}"
    try:
        # GET 默认：新会话（文件不存在=空白）；默认 minimal-standard
        status, data = _request(
            port, "GET", f"{base}/session-modes?session=conversation-1.jsonl")
        assert status == 200, data
        d = json.loads(data)
        assert d == {"mode": "minimal", "variant": "standard",
                     "source": "default", "editable": True,
                     "picker_enabled": True, "default_mode": "minimal-standard"}
        # PUT 切换（空白会话允许）
        status, data = _request(
            port, "PUT", f"{base}/session-modes?session=conversation-1.jsonl",
            {"mode": "minimal", "variant": "pure"})
        assert status == 200, data
        d = json.loads(data)
        assert (d["mode"], d["variant"], d["source"]) == (
            "minimal", "pure", "session")
        assert d["editable"] is True
        # sidecar 落盘（原子写）
        side = json.loads((wd / ".wuxing" / "session-modes.json")
                          .read_text(encoding="utf-8"))
        row = side["conversations"]["conversation-1.jsonl"]
        assert row["mode"] == "minimal" and row["variant"] == "pure"
        # 再 GET → 会话级生效
        status, data = _request(
            port, "GET", f"{base}/session-modes?session=conversation-1.jsonl")
        assert json.loads(data)["source"] == "session"
    finally:
        srv.stop()


def test_session_modes_put_rejects_non_blank(tmp_path):
    from wuxing.conversation import ConversationState
    srv, port, mgr = _mk_server(tmp_path)
    ws, wd = _open(tmp_path, mgr)
    st = ConversationState(wd / ".wuxing" / "conversation-1.jsonl")
    st.append_turn(1, "第一轮需求", [], "完成")
    base = f"/api/v1/workspaces/{ws['id']}"
    try:
        status, data = _request(
            port, "PUT", f"{base}/session-modes?session=conversation-1.jsonl",
            {"mode": "minimal", "variant": "pure"})
        assert status == 422, data
        err = json.loads(data)["error"]
        assert err["code"] == "session/not-blank"
        # GET：editable=False（机制守卫可见）
        status, data = _request(
            port, "GET", f"{base}/session-modes?session=conversation-1.jsonl")
        assert json.loads(data)["editable"] is False
        # 拒绝后 sidecar 不落盘（未写入）
        assert not (wd / ".wuxing" / "session-modes.json").exists()
    finally:
        srv.stop()


def test_session_modes_put_rejects_unknown_and_bad_session(tmp_path):
    srv, port, mgr = _mk_server(tmp_path)
    ws, _wd = _open(tmp_path, mgr)
    base = f"/api/v1/workspaces/{ws['id']}"
    try:
        # 未知 mode/variant → 422
        status, data = _request(
            port, "PUT", f"{base}/session-modes?session=c1.jsonl",
            {"mode": "nope", "variant": "pure"})
        assert status == 422 and json.loads(data)["error"]["code"] == "invalid"
        status, data = _request(
            port, "PUT", f"{base}/session-modes?session=c1.jsonl",
            {"mode": "minimal", "variant": "nope"})
        assert status == 422
        # 未知键 → 422
        status, data = _request(
            port, "PUT", f"{base}/session-modes?session=c1.jsonl",
            {"mode": "minimal", "variant": "pure", "extra": 1})
        assert status == 422
        # 缺 session / 非法会话名 → 422
        status, _ = _request(port, "GET", f"{base}/session-modes")
        assert status == 422
        status, _ = _request(
            port, "PUT", f"{base}/session-modes?session=../evil.jsonl",
            {"mode": "minimal", "variant": "pure"})
        assert status == 422
        status, _ = _request(
            port, "GET", f"{base}/session-modes?session=trace.jsonl")
        assert status == 422
    finally:
        srv.stop()
