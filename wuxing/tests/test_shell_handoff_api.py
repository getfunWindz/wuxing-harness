"""TDD（双模式批 4 · Task 2）：承接简报端点（GET + 校验）。"""
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


def test_handoff_brief_endpoint(tmp_path):
    srv, port, mgr = _mk_server(tmp_path)
    wd = tmp_path / "proj"
    wd.mkdir()
    (wd / ".wuxing").mkdir()
    ws = mgr.open_workspace(str(wd))
    base = f"/api/v1/workspaces/{ws['id']}"
    try:
        # 缺 session → 422；非法名 → 422
        status, _ = _request(port, "GET", f"{base}/handoff-brief")
        assert status == 422
        status, _ = _request(
            port, "GET", f"{base}/handoff-brief?session=trace.jsonl")
        assert status == 422
        # 无会话文件 → available False（不造假）
        status, data = _request(
            port, "GET", f"{base}/handoff-brief?session=conversation-1.jsonl")
        assert status == 200, data
        d = json.loads(data)
        assert d == {"available": False,
                     "source_session": "conversation-1.jsonl",
                     "rounds": 0, "brief": ""}
        # 写两轮会话 → 简报在场（轮次/来源/继续指令）
        from wuxing.conversation import ConversationState
        st = ConversationState(wd / ".wuxing" / "conversation-1.jsonl")
        st.append_turn(1, "先做一个发布工具", ["artifacts/a.md"], "完成 A")
        st.append_turn(2, "再加一个校验", [], "完成 B")
        status, data = _request(
            port, "GET", f"{base}/handoff-brief?session=conversation-1.jsonl")
        d2 = json.loads(data)
        assert d2["available"] is True and d2["rounds"] == 2
        assert "[新会话承接简报]" in d2["brief"]
        assert "先做一个发布工具" in d2["brief"] and "继续指令" in d2["brief"]
    finally:
        srv.stop()
