"""R3-1 凭据 API：write-only（响应永不含值）、env 遮蔽 409、幂等删除。"""
import http.client
import json

import pytest


@pytest.fixture(autouse=True)
def _store(tmp_path, monkeypatch):
    import wuxing.credentials as creds
    monkeypatch.setattr(creds, "credentials_path",
                        lambda: tmp_path / "credentials.json")
    monkeypatch.delenv("WUXING_TEST_KEY", raising=False)
    return creds


def _mk_server(tmp_path):
    from wuxing.shell.web.api import register_api
    from wuxing.shell.web.hub import EventHub
    from wuxing.shell.web.manager import EngineManager
    from wuxing.shell.web.server import ShellServer

    class _Eng:
        def __init__(self, workdir, auto_confirm=False):
            self.workdir = workdir

    hub = EventHub()
    mgr = EngineManager(hub=hub, engine_factory=lambda wd, ac: _Eng(wd, ac),
                        state_path=tmp_path / "ws.json")
    srv = ShellServer(port=0, hub=hub)
    register_api(srv, mgr)
    return srv, srv.start(), mgr


def _req(port, method, path, body=None):
    c = http.client.HTTPConnection("127.0.0.60", port, timeout=5)
    headers = ({} if method == "GET"
               else {"X-Wuxing": "1", "Content-Type": "application/json"})
    c.request(method, path, body=body, headers=headers)
    r = c.getresponse()
    raw = r.read()
    status = r.status
    c.close()
    return status, raw


def test_credentials_roundtrip_never_exposes_value(tmp_path, _store):
    srv, port, mgr = _mk_server(tmp_path)
    try:
        status, raw = _req(port, "PUT", "/api/v1/credentials/WUXING_TEST_KEY",
                           body=json.dumps({"value": "sk-secret-material"}))
        assert status == 200, raw
        assert b"sk-secret-material" not in raw
        out = json.loads(raw)
        assert out["configured"] is True and out["source"] == "store"

        status, raw = _req(port, "GET", "/api/v1/credentials/WUXING_TEST_KEY")
        assert status == 200
        assert b"sk-secret-material" not in raw
        assert json.loads(raw)["configured"] is True

        status, _ = _req(port, "DELETE", "/api/v1/credentials/WUXING_TEST_KEY")
        assert status == 200
        status, raw = _req(port, "GET", "/api/v1/credentials/WUXING_TEST_KEY")
        assert json.loads(raw)["configured"] is False
    finally:
        srv.stop()
        mgr.shutdown()


def test_credentials_shadowed_409(tmp_path, _store, monkeypatch):
    monkeypatch.setenv("WUXING_TEST_KEY", "sk-env")
    srv, port, mgr = _mk_server(tmp_path)
    try:
        status, raw = _req(port, "PUT", "/api/v1/credentials/WUXING_TEST_KEY",
                           body=json.dumps({"value": "sk-x"}))
        assert status == 409, raw
        assert json.loads(raw)["error"]["code"] == "credential/shadowed"
    finally:
        srv.stop()
        mgr.shutdown()


def test_credentials_invalid_422(tmp_path, _store):
    srv, port, mgr = _mk_server(tmp_path)
    try:
        status, _ = _req(port, "PUT", "/api/v1/credentials/lower",
                         body=json.dumps({"value": "sk-x"}))
        assert status == 422
        status, _ = _req(port, "PUT", "/api/v1/credentials/WUXING_TEST_KEY",
                         body=json.dumps({"value": "NAME=sk-x"}))
        assert status == 422
    finally:
        srv.stop()
        mgr.shutdown()
