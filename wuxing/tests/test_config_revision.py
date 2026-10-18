"""R3-1：providers 配置段 + revision 冲突协议 + 字段保留语义。"""
import pytest

from wuxing.config_contract import (
    ConfigConflict,
    config_revision,
    effective_config,
    write_config,
)
from wuxing.config_schema import validate_config


@pytest.fixture(autouse=True)
def _user_cfg(tmp_path, monkeypatch):
    import wuxing.config_contract as cc
    path = tmp_path / "config.jsonc"
    monkeypatch.setattr(cc, "user_config_path", lambda: path)
    return path


def test_providers_valid_entries():
    errs = validate_config({"providers": {
        "deepseek": {"type": "deepseek"},
        "micu-claude": {"type": "anthropic", "base_url": "https://api.micuapi.ai",
                        "credential_ref": "MICU_CLAUDE_KEY",
                        "display_name": "中转·Claude",
                        "models": [{"id": "claude-sonnet-5", "display_name": "Sonnet 5",
                                    "context_window": 200000, "max_tokens": 8192}]},
    }})
    assert errs == []


def test_providers_rejects_bad_entries():
    errs = validate_config({"providers": {
        "bad id!": {"type": "deepseek"},
        "mocked": {"type": "mock"},
        "badurl": {"type": "openai", "base_url": "ftp://x/v1"},
        "badref": {"type": "openai", "credential_ref": "lower"},
        "badmodels": {"type": "openai", "models": [{"id": ""}]},
        "badcap": {"type": "openai", "models": [{"id": "m", "context_window": -1}]},
    }})
    joined = "\n".join(errs)
    assert "bad id!" in joined
    assert "mocked" in joined and "mock" in joined
    assert "badurl" in joined and "http" in joined
    assert "badref" in joined
    assert "badmodels" in joined
    assert "badcap" in joined


def test_providers_default_in_effective_config():
    assert effective_config(None)["values"]["providers"] == {}


def test_revision_empty_then_write_and_conflict(_user_cfg):
    assert config_revision() == ""
    out = write_config("user", {"providers": {"a": {"type": "openai"}}})
    r1 = out["revision"]
    assert r1 and config_revision() == r1
    with pytest.raises(ConfigConflict) as ei:
        write_config("user", {"providers": {}}, replace_keys=["providers"],
                     revision="stale-rev")
    assert ei.value.current_revision == r1


def test_external_edit_detected(_user_cfg):
    write_config("user", {"providers": {"a": {"type": "openai"}}})
    r = config_revision()
    _user_cfg.write_text(
        '{\n  "providers": {"a": {"type": "openai"}, "b": {"type": "anthropic"}}\n}\n',
        encoding="utf-8")
    assert config_revision() != r
    with pytest.raises(ConfigConflict):
        write_config("user", {"providers": {"a": {"type": "openai"}}}, revision=r)


def test_write_without_revision_compat(_user_cfg):
    write_config("user", {"providers": {"a": {"type": "openai"}}})
    out = write_config("user", {"providers": {"a": {"type": "openai",
                                                    "display_name": "A"}}})
    assert out["revision"] == config_revision()
    assert effective_config(None)["values"]["providers"]["a"]["display_name"] == "A"


def test_provider_edit_preserves_siblings_and_hidden_fields(_user_cfg):
    write_config("user", {"providers": {
        "a": {"type": "openai", "base_url": "https://a/v1",
              "display_name": "A", "headers": {"X-Deploy": "1"}},
        "b": {"type": "anthropic"}}})
    r = config_revision()
    write_config("user", {"providers": {"a": {
        "type": "openai", "base_url": "https://a2/v1", "display_name": "A",
        "headers": {"X-Deploy": "1"},
        "models": [{"id": "gpt-x"}]}}}, revision=r)
    data = effective_config(None)["values"]["providers"]
    assert data["b"] == {"type": "anthropic"}            # 兄弟条目保留
    assert data["a"]["models"] == [{"id": "gpt-x"}]
    assert data["a"]["base_url"] == "https://a2/v1"
    assert data["a"]["headers"] == {"X-Deploy": "1"}     # 编辑器未展示字段保留


def test_providers_replace_semantics_delete(_user_cfg):
    write_config("user", {"providers": {"a": {"type": "openai"},
                                        "b": {"type": "anthropic"}}})
    write_config("user", {"providers": {"a": {"type": "openai"}}},
                 replace_keys=["providers"])
    assert set(effective_config(None)["values"]["providers"]) == {"a"}


def test_shell_config_endpoint_revision_roundtrip(tmp_path):
    """端点层：GET 带 revision；PUT 携带过期 revision → 409 config/conflict。"""
    import http.client
    import json as _json

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
    port = srv.start()

    def _req(method, path, body=None):
        c = http.client.HTTPConnection("127.0.0.60", port, timeout=5)
        headers = ({} if method == "GET"
                   else {"X-Wuxing": "1", "Content-Type": "application/json"})
        c.request(method, path, body=body, headers=headers)
        r = c.getresponse()
        data = _json.loads(r.read())
        status = r.status
        c.close()
        return status, data

    try:
        status, data = _req("GET", "/api/v1/config")
        assert status == 200 and "revision" in data

        status, out = _req("PUT", "/api/v1/config?scope=user", body=_json.dumps(
            {"values": {"providers": {"a": {"type": "openai"}}}}))
        assert status == 200 and out["revision"]

        status, err = _req("PUT", "/api/v1/config?scope=user", body=_json.dumps(
            {"values": {"providers": {}}, "replace": ["providers"],
             "revision": "stale-rev"}))
        assert status == 409
        assert err["error"]["code"] == "config/conflict"
    finally:
        srv.stop()
        mgr.shutdown()


def test_provider_model_refs_accepted_by_schema():
    """R5-1：llm/router 的 provider/model 引用形式通过校验（存在性由引擎解析期报错）。"""
    assert validate_config({"llm": "demo-provider/demo-model"}) == []
    assert validate_config({"router": {"verify": "micu-claude/claude-sonnet-5"}}) == []
    assert validate_config({"router": {"verify": {"provider": "micu-claude",
                                                  "model": "claude-sonnet-5"}}}) == []
    errs = validate_config({"router": {"verify": {"provider": "", "model": "m"}}})
    assert any("provider" in e for e in errs)
    assert validate_config({"llm": "hugo:gpt"})  # 旧格式非法类型仍被拦截
