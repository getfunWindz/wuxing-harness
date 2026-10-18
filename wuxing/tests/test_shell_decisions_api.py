"""#2 T-5：决策历史 API（GET /api/v1/workspaces/{ws}/decisions）。"""
import http.client
import json

from wuxing.shell.web.hub import EventHub


class _FakeEngine:
    def __init__(self, workdir, auto_confirm=False):
        self.workdir = workdir


def _mk_server(tmp_path):
    from wuxing.shell.web.api import register_api
    from wuxing.shell.web.manager import EngineManager
    from wuxing.shell.web.server import ShellServer
    hub = EventHub()
    mgr = EngineManager(hub=hub, engine_factory=lambda w, a: _FakeEngine(w, a),
                        state_path=tmp_path / "ws.json")
    srv = ShellServer(port=0, hub=hub)
    register_api(srv, mgr)
    port = srv.start()
    return srv, port, mgr


def _request(port, method, path):
    c = http.client.HTTPConnection("127.0.0.60", port, timeout=5)
    c.request(method, path)
    r = c.getresponse()
    raw = r.read()
    c.close()
    return r.status, (json.loads(raw.decode("utf-8")) if raw else {})


def test_decisions_endpoint(tmp_path):
    wd = tmp_path / "proj"
    (wd / ".wuxing").mkdir(parents=True)
    (wd / ".wuxing" / "trace.jsonl").write_text(json.dumps(
        {"ts": 2.0, "event": "confirm_decided", "unit_id": "U-1",
         "domain": "verify", "decision": "approve", "reason": ""}) + "\n",
        encoding="utf-8")
    srv, port, mgr = _mk_server(tmp_path)
    try:
        ws_id = mgr.open_workspace(str(wd))["id"]
        status, data = _request(port, "GET",
                                f"/api/v1/workspaces/{ws_id}/decisions")
        assert status == 200
        assert data["entries"][0]["status"] == "approved"
        assert data["entries"][0]["object"] == "U-1"
    finally:
        srv.stop()
