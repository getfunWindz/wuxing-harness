"""R3-1 发现端点：一次性凭据（草稿 key）> credential_ref 解析；key 不回显。"""
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


def test_discover_one_shot_key_not_echoed(tmp_path, monkeypatch):
    from wuxing.shell.web.api_routes import providers
    seen = {}

    def fake(base_url, ptype, api_key=None, timeout=30.0):
        seen.update(base_url=base_url, ptype=ptype, api_key=api_key)
        return [{"id": "m1"}]

    monkeypatch.setattr(providers, "discover_models", fake)
    srv, port, mgr = _mk_server(tmp_path)
    try:
        status, raw = _req(port, "POST", "/api/v1/providers/discover", body=json.dumps(
            {"base_url": "https://api.deepseek.com", "type": "deepseek",
             "key": "sk-draft-secret"}))
        assert status == 200, raw
        assert b"sk-draft-secret" not in raw
        assert json.loads(raw)["models"] == [{"id": "m1"}]
        assert seen["api_key"] == "sk-draft-secret"
    finally:
        srv.stop()
        mgr.shutdown()


def test_discover_credential_ref_from_store(tmp_path, monkeypatch, _store):
    from wuxing.shell.web.api_routes import providers
    _store.set("WUXING_TEST_KEY", "sk-store-value")
    seen = {}

    def fake(base_url, ptype, api_key=None, timeout=30.0):
        seen["api_key"] = api_key
        return []

    monkeypatch.setattr(providers, "discover_models", fake)
    srv, port, mgr = _mk_server(tmp_path)
    try:
        status, _ = _req(port, "POST", "/api/v1/providers/discover", body=json.dumps(
            {"base_url": "https://x/v1", "type": "openai",
             "credential_ref": "WUXING_TEST_KEY"}))
        assert status == 200
        assert seen["api_key"] == "sk-store-value"
    finally:
        srv.stop()
        mgr.shutdown()


def test_discover_validation_and_upstream_failure(tmp_path, monkeypatch):
    from wuxing.shell.web.api_routes import providers
    from wuxing.shell.web.provider_probe import ProbeError

    srv, port, mgr = _mk_server(tmp_path)
    try:
        status, _ = _req(port, "POST", "/api/v1/providers/discover",
                         body=json.dumps({"type": "openai"}))
        assert status == 422
        status, _ = _req(port, "POST", "/api/v1/providers/discover",
                         body=json.dumps({"base_url": "ftp://x/v1", "type": "openai"}))
        assert status == 422

        def boom(*a, **k):
            raise ProbeError("端点返回 HTTP 500（检查端点与凭据）")

        monkeypatch.setattr(providers, "discover_models", boom)
        status, raw = _req(port, "POST", "/api/v1/providers/discover", body=json.dumps(
            {"base_url": "https://x/v1", "type": "openai"}))
        assert status == 502
        assert json.loads(raw)["error"]["code"] == "provider/discovery-failed"
    finally:
        srv.stop()
        mgr.shutdown()


def test_providers_catalog_endpoint(tmp_path):
    srv, port, mgr = _mk_server(tmp_path)
    try:
        status, raw = _req(port, "GET", "/api/v1/providers/catalog")
        assert status == 200, raw
        data = json.loads(raw)
        ids = [p["id"] for p in data["providers"]]
        assert "deepseek" in ids and "ollama" in ids and "anthropic" in ids
        for p in data["providers"]:
            assert p["base_url"].startswith("http")
            assert p["docs"].startswith("https://")
    finally:
        srv.stop()
        mgr.shutdown()
