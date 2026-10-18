"""TDD：#3 域提示词 API（GET/POST /api/v1/prompts/domains）。"""
import http.client
import json

from wuxing import domain_prompts
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
    user = tmp_path / "user.json"
    ws = tmp_path / "prompt-ws.json"
    monkeypatch.setattr(domain_prompts, "user_store_path", lambda: user)
    monkeypatch.setattr(domain_prompts, "workspace_store_path", lambda root: ws)


def test_get_lists_domains_and_builtin_defaults(tmp_path, monkeypatch):
    wd = tmp_path / "proj"; wd.mkdir()
    _patch_stores(tmp_path, monkeypatch)
    srv, port, mgr = _mk_server(tmp_path)
    try:
        ws_id = mgr.open_workspace(str(wd))["id"]
        status, data = _request(port, "GET",
                                f"/api/v1/prompts/domains?ws={ws_id}")
        assert status == 200
        assert [e["domain"] for e in data["entries"]] == [
            "plan", "execute", "verify", "user", "design"]
        assert data["entries"][0]["builtin_notes"], "内置默认必须可见"
        assert data["problems"] == []
    finally:
        srv.stop()


def test_post_saves_workspace_scope_and_returns_effective(tmp_path, monkeypatch):
    wd = tmp_path / "proj"; wd.mkdir()
    _patch_stores(tmp_path, monkeypatch)
    srv, port, mgr = _mk_server(tmp_path)
    try:
        ws_id = mgr.open_workspace(str(wd))["id"]
        status, data = _request(
            port, "POST", "/api/v1/prompts/domains",
            {"scope": "workspace", "ws": ws_id,
             "values": {"verify": {"notes": "工作区注记"}}}, mutate=True)
        assert status == 200
        ent = next(e for e in data["entries"] if e["domain"] == "verify")
        assert ent["notes_effective"] == "工作区注记"
        assert ent["notes_source"] == "workspace"
    finally:
        srv.stop()


def test_post_rejects_oversize_and_unknown_domain(tmp_path, monkeypatch):
    wd = tmp_path / "proj"; wd.mkdir()
    _patch_stores(tmp_path, monkeypatch)
    srv, port, mgr = _mk_server(tmp_path)
    try:
        ws_id = mgr.open_workspace(str(wd))["id"]
        status, _ = _request(
            port, "POST", "/api/v1/prompts/domains",
            {"scope": "workspace", "ws": ws_id,
             "values": {"verify": {"notes": "y" * 2001}}}, mutate=True)
        assert status == 422
        status, _ = _request(
            port, "POST", "/api/v1/prompts/domains",
            {"scope": "user", "values": {"nope": {"notes": "x"}}}, mutate=True)
        assert status == 422
    finally:
        srv.stop()
