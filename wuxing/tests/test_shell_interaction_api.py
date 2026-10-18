"""#2 Phase 1.5：交互偏好 API（GET/POST /api/v1/interaction）。"""
import http.client
import json

from wuxing import interaction_prefs
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


def _request(port, method, path, body=None, mutate=False):
    headers = {"X-Wuxing": "1", "Content-Type": "application/json"} \
        if mutate else {}
    c = http.client.HTTPConnection("127.0.0.60", port, timeout=5)
    c.request(method, path,
              body=json.dumps(body) if body is not None else None,
              headers=headers)
    r = c.getresponse()
    raw = r.read()
    status = r.status
    c.close()
    return status, (json.loads(raw.decode("utf-8")) if raw else {})


def _patch_stores(tmp_path, monkeypatch):
    user = tmp_path / "prefs-user.json"
    ws = tmp_path / "prefs-ws.json"
    monkeypatch.setattr(interaction_prefs, "user_store_path", lambda: user)
    monkeypatch.setattr(interaction_prefs, "workspace_store_path",
                        lambda root: ws)


def test_get_defaults_and_post_user_scope(tmp_path, monkeypatch):
    _patch_stores(tmp_path, monkeypatch)
    srv, port, _mgr = _mk_server(tmp_path)
    try:
        status, data = _request(port, "GET", "/api/v1/interaction")
        assert status == 200
        assert data["effective"]["confirm_verbosity"] == "standard"
        assert data["sources"]["confirm_verbosity"] == "default"
        status, data = _request(port, "POST", "/api/v1/interaction",
                                {"scope": "user",
                                 "values": {"confirm_verbosity": "concise"}},
                                mutate=True)
        assert status == 200
        assert data["effective"]["confirm_verbosity"] == "concise"
        assert data["sources"]["confirm_verbosity"] == "user"
    finally:
        srv.stop()


def test_workspace_scope_and_validation(tmp_path, monkeypatch):
    _patch_stores(tmp_path, monkeypatch)
    srv, port, mgr = _mk_server(tmp_path)
    try:
        wd = tmp_path / "proj"
        wd.mkdir()
        ws_id = mgr.open_workspace(str(wd))["id"]
        status, data = _request(
            port, "POST", "/api/v1/interaction",
            {"scope": "workspace", "ws": ws_id,
             "values": {"details_default_open": True}}, mutate=True)
        assert status == 200
        assert data["sources"]["details_default_open"] == "workspace"
        status, data = _request(port, "POST", "/api/v1/interaction",
                                {"scope": "workspace",
                                 "values": {"details_default_open": True}},
                                mutate=True)
        assert status == 422, "工作区级写入缺 ws → 拒绝"
        status, data = _request(port, "POST", "/api/v1/interaction",
                                {"scope": "user",
                                 "values": {"confirm_verbosity": "fancy"}},
                                mutate=True)
        assert status == 422
    finally:
        srv.stop()


def test_confirm_notify_scope_and_receipt(tmp_path, monkeypatch):
    _patch_stores(tmp_path, monkeypatch)
    srv, port, _mgr = _mk_server(tmp_path)
    try:
        status, data = _request(port, "POST", "/api/v1/interaction",
                                {"scope": "user",
                                 "values": {"confirm_notify": True}},
                                mutate=True)
        assert status == 200
        assert data["effective"]["confirm_notify"] is True
        assert data["sources"]["confirm_notify"] == "user"
        status, data = _request(port, "POST", "/api/v1/interaction",
                                {"scope": "user",
                                 "values": {"confirm_notify": "yes"}},
                                mutate=True)
        assert status == 422
    finally:
        srv.stop()
