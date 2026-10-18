"""R3-1 模型发现探询：协议头/解析宽容/去重保序/错误分类（不回显 key）。"""
import urllib.error

import pytest

import wuxing.shell.web.provider_probe as pp


class _Resp:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake_urlopen(payload: bytes, calls: list):
    def _open(req, timeout=None):
        calls.append(req)
        return _Resp(payload)
    return _open


def _headers(req) -> dict:
    return {k.lower(): v for k, v in req.headers.items()}


def test_openai_like_headers_and_parse(monkeypatch):
    calls = []
    monkeypatch.setattr(pp.urllib.request, "urlopen",
                        _fake_urlopen(b'{"data": [{"id": "a"}, {"id": "b"}]}', calls))
    out = pp.discover_models("https://api.deepseek.com", "deepseek", "sk-1")
    assert [m["id"] for m in out] == ["a", "b"]
    req = calls[0]
    assert req.full_url == "https://api.deepseek.com/models"
    assert _headers(req)["authorization"] == "Bearer sk-1"


def test_anthropic_headers_and_trailing_slash(monkeypatch):
    calls = []
    monkeypatch.setattr(pp.urllib.request, "urlopen",
                        _fake_urlopen(b'{"data": [{"id": "claude-x"}]}', calls))
    out = pp.discover_models("https://api.anthropic.com/v1/", "anthropic", "sk-2")
    assert [m["id"] for m in out] == ["claude-x"]
    req = calls[0]
    assert req.full_url == "https://api.anthropic.com/v1/models"
    h = _headers(req)
    assert h["x-api-key"] == "sk-2"
    assert h["anthropic-version"] == pp.ANTHROPIC_VERSION


def test_rich_models_object_and_dedupe_order(monkeypatch):
    calls = []
    payload = (b'{"models": {"m1": {"display_name": "M One", "context_window": 1000},'
               b' "m2": {"display_name": "m2"}}}')
    monkeypatch.setattr(pp.urllib.request, "urlopen", _fake_urlopen(payload, calls))
    out = pp.discover_models("https://x/v1", "openai", None)
    assert out == [{"id": "m1", "display_name": "M One", "context_window": 1000},
                   {"id": "m2"}]

    calls2 = []
    monkeypatch.setattr(pp.urllib.request, "urlopen",
                        _fake_urlopen(b'{"data": [{"id": "a"}, {"id": "a"}, {"id": "b"}]}',
                                      calls2))
    assert [m["id"] for m in pp.discover_models("https://x/v1", "openai")] == ["a", "b"]


def test_http_error_is_classified_without_key(monkeypatch):
    def _raise(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, None)
    monkeypatch.setattr(pp.urllib.request, "urlopen", _raise)
    with pytest.raises(pp.ProbeError) as ei:
        pp.discover_models("https://x/v1", "openai", "sk-secret-value")
    assert "401" in str(ei.value)
    assert "sk-secret-value" not in str(ei.value)


def test_bad_url_and_mock_rejected(monkeypatch):
    with pytest.raises(pp.ProbeError):
        pp.discover_models("ftp://x/v1", "openai")
    with pytest.raises(pp.ProbeError):
        pp.discover_models("https://x/v1", "mock")


def test_non_json_rejected(monkeypatch):
    calls = []
    monkeypatch.setattr(pp.urllib.request, "urlopen",
                        _fake_urlopen(b"<html>nope</html>", calls))
    with pytest.raises(pp.ProbeError):
        pp.discover_models("https://x/v1", "openai")
