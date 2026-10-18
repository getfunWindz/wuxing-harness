"""TDD · §11.5-①：浏览器身份 API（GET /api/v1/browser/identity；POST .../clear）。"""
import http.client
import json

from wuxing import browser_identity
from wuxing.shell.web.api_routes import browser_api
from wuxing.shell.web.hub import EventHub


class _FakeEngine:
    def __init__(self, workdir, auto_confirm=False):
        self.workdir = workdir


class _FakeChannel:
    def __init__(self):
        self.calls = []

    def call(self, cmd, timeout=None, **args):
        self.calls.append((cmd, dict(args)))
        return {"cleared": True, "key": args.get("key")}


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


def _patch_registry(tmp_path, monkeypatch):
    reg = tmp_path / "browser_identity_registry.json"
    monkeypatch.setattr(browser_identity, "registry_path", lambda: reg)
    return reg


def test_identity_get_lists_registry_and_mode(tmp_path, monkeypatch):
    wd = tmp_path / "proj"; wd.mkdir()
    reg = _patch_registry(tmp_path, monkeypatch)
    reg.write_text(json.dumps({"version": 1, "entries": [
        {"key": "wuxing-browser-x", "workspace": str(wd), "mode": "persist",
         "first_used_at": "T1", "last_used_at": "T2"}]}), encoding="utf-8")
    srv, port, mgr = _mk_server(tmp_path)
    try:
        ws_id = mgr.open_workspace(str(wd))["id"]
        status, data = _request(port, "GET",
                                f"/api/v1/browser/identity?ws={ws_id}")
        assert status == 200
        assert data["mode"] == "memory"
        assert data["current_key"].startswith("wuxing-browser-")
        assert data["entries"][0]["key"] == "wuxing-browser-x"
        assert data["problems"] == []
    finally:
        srv.stop()


def test_identity_clear_uses_channel(tmp_path, monkeypatch):
    reg = _patch_registry(tmp_path, monkeypatch)
    reg.write_text(json.dumps({"version": 1, "entries": [
        {"key": "wuxing-browser-x", "workspace": "C:/p", "mode": "persist",
         "first_used_at": "T1", "last_used_at": "T2"}]}), encoding="utf-8")
    fake = _FakeChannel()
    monkeypatch.setattr(browser_api, "_channel_client", lambda: fake)
    srv, port, _ = _mk_server(tmp_path)
    try:
        status, data = _request(port, "POST", "/api/v1/browser/identity/clear",
                                {"key": "wuxing-browser-x"}, mutate=True)
        assert status == 200 and data["removed_key"] == "wuxing-browser-x"
        assert fake.calls == [("identity_clear", {"key": "wuxing-browser-x"})]
    finally:
        srv.stop()


def test_identity_clear_no_channel_loud(tmp_path, monkeypatch):
    _patch_registry(tmp_path, monkeypatch)
    monkeypatch.setattr(browser_api, "_channel_client", lambda: None)
    srv, port, _ = _mk_server(tmp_path)
    try:
        status, data = _request(port, "POST", "/api/v1/browser/identity/clear",
                                {"key": "wuxing-browser-x"}, mutate=True)
        assert status == 503 and "桌面壳" in data["error"]["message"]
    finally:
        srv.stop()


def test_identity_clear_bad_key(tmp_path, monkeypatch):
    _patch_registry(tmp_path, monkeypatch)
    srv, port, _ = _mk_server(tmp_path)
    try:
        status, _ = _request(port, "POST", "/api/v1/browser/identity/clear",
                             {"key": "BAD KEY"}, mutate=True)
        assert status == 422
    finally:
        srv.stop()


def test_identity_clear_channel_error_visible(tmp_path, monkeypatch):
    from wuxing.browser_channel import BrowserChannelError
    _patch_registry(tmp_path, monkeypatch)

    class _Boom:
        def call(self, cmd, timeout=None, **args):
            raise BrowserChannelError("unreachable", "控制通道不可达：boom")

    monkeypatch.setattr(browser_api, "_channel_client", lambda: _Boom())
    srv, port, _ = _mk_server(tmp_path)
    try:
        status, data = _request(port, "POST", "/api/v1/browser/identity/clear",
                                {"key": "wuxing-browser-x"}, mutate=True)
        assert status == 502 and "不可达" in data["error"]["message"]
    finally:
        srv.stop()


# ---- O2-2 §11.5-③：identity GET 返回 storage-state 摘要（值纪律） ----


def test_identity_get_storage_state_summary(tmp_path, monkeypatch):
    wd = tmp_path / "proj"
    wd.mkdir()
    state = tmp_path / "state.json"
    state.write_text(json.dumps({
        "cookies": [{"name": "sid", "value": "secret-1",
                     "domain": "127.0.0.1", "path": "/"}],
        "origins": [{"origin": "http://127.0.0.1:1",
                     "localStorage": [{"name": "k", "value": "secret-2"}]}],
    }), encoding="utf-8")
    (wd / "config.jsonc").write_text(json.dumps({
        "browser_identity_mode": "storage-state",
        "browser_storage_state_path": str(state)}), encoding="utf-8")
    _patch_registry(tmp_path, monkeypatch)
    srv, port, mgr = _mk_server(tmp_path)
    try:
        ws_id = mgr.open_workspace(str(wd))["id"]
        status, data = _request(port, "GET",
                                f"/api/v1/browser/identity?ws={ws_id}")
        assert status == 200 and data["mode"] == "storage-state"
        s = data["storage_state"]
        assert s["valid"] is True and s["cookies"] == 1 and s["origins"] == 1
        assert s["path"] == str(state) and s["error"] == ""
        dumped = json.dumps(data)
        assert "secret-1" not in dumped and "secret-2" not in dumped
    finally:
        srv.stop()


def test_identity_get_storage_state_invalid_error(tmp_path, monkeypatch):
    wd = tmp_path / "proj2"
    wd.mkdir()
    (wd / "config.jsonc").write_text(json.dumps({
        "browser_identity_mode": "storage-state",
        "browser_storage_state_path": str(tmp_path / "missing.json")}),
        encoding="utf-8")
    _patch_registry(tmp_path, monkeypatch)
    srv, port, mgr = _mk_server(tmp_path)
    try:
        ws_id = mgr.open_workspace(str(wd))["id"]
        status, data = _request(port, "GET",
                                f"/api/v1/browser/identity?ws={ws_id}")
        assert status == 200
        assert data["storage_state"]["valid"] is False
        assert data["storage_state"]["error"]
    finally:
        srv.stop()
