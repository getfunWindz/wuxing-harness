"""TDD：壳服务远程鉴权档（O5 安全门 T1/T2）。

设计：`docs/WUXING_O5内网穿透研究_2026-10-15.md` §4/§8-T1。
"""
import http.client
import logging

import pytest

from wuxing.shell.web.auth import (
    SESSION_COOKIE,
    AuthGuard,
    cookie_token,
    is_loopback_host,
    resolve_shell_token,
    token_from_headers,
)

# ---- T1：模块级 ----

def test_is_loopback_host():
    assert is_loopback_host("127.0.0.60")
    assert is_loopback_host("127.0.0.1")
    assert is_loopback_host("::1")
    assert is_loopback_host("localhost")
    assert not is_loopback_host("0.0.0.0")
    assert not is_loopback_host("192.168.1.5")
    assert not is_loopback_host("")


def test_token_resolution_order(monkeypatch):
    monkeypatch.delenv("WUXING_SHELL_TOKEN", raising=False)
    assert resolve_shell_token() is None
    assert resolve_shell_token("explicit") == "explicit"
    monkeypatch.setenv("WUXING_SHELL_TOKEN", "env-token")
    assert resolve_shell_token() == "env-token"
    assert resolve_shell_token("explicit") == "explicit"  # 显式优先


def test_token_from_headers():
    assert token_from_headers({"Authorization": "Bearer abc"}) == "abc"
    assert token_from_headers({"Authorization": "bearer abc"}) == "abc"
    assert token_from_headers({"X-Wuxing-Token": "xyz"}) == "xyz"
    assert token_from_headers(
        {"Authorization": "Basic abc", "X-Wuxing-Token": "xyz"}) == "xyz"
    assert token_from_headers({}) is None
    assert token_from_headers({"Authorization": "Basic abc"}) is None


def test_cookie_token():
    assert cookie_token(f"a=1; {SESSION_COOKIE}=tok; b=2") == "tok"
    assert cookie_token("") is None
    assert cookie_token("nope=1") is None


def test_guard_verify():
    g = AuthGuard("secret")
    assert g.verify("secret")
    assert not g.verify("wrong")
    assert not g.verify(None)
    assert not g.verify("")
    with pytest.raises(ValueError):
        AuthGuard("")


def test_guard_rate_limit_with_fake_clock():
    now = [0.0]
    g = AuthGuard("s", max_failures=3, window_s=10.0, clock=lambda: now[0])
    assert not g.is_rate_limited("ip1")
    assert not g.note_failure("ip1")
    assert not g.note_failure("ip1")
    assert g.note_failure("ip1")            # 第 3 次触发
    assert g.is_rate_limited("ip1")
    assert not g.is_rate_limited("ip2")     # 按 IP 独立
    now[0] = 11.0                            # 窗口滑出 → 自愈
    assert not g.is_rate_limited("ip1")


def test_rate_limit_trip_logs(caplog):
    g = AuthGuard("s", max_failures=1)
    with caplog.at_level(logging.WARNING, logger="wuxing.shell.auth"):
        g.note_failure("10.0.0.9")
    assert "rate_limited" in caplog.text
    assert "10.0.0.9" in caplog.text


# ---- T2：服务接线 ----

def _mk_auth_server(token="secret", **kwargs):
    from wuxing.shell.web.hub import EventHub
    from wuxing.shell.web.server import ShellServer

    def ping(req):
        return {"pong": True}

    srv = ShellServer(port=0, hub=EventHub(), auth=AuthGuard(token), **kwargs)
    srv.add_route("GET", "^/ping$", ping)
    srv.add_route("POST", "^/ping$", ping)
    return srv, srv.start()


def _req(port, method="GET", path="/ping", headers=None):
    c = http.client.HTTPConnection("127.0.0.60", port, timeout=5)
    c.request(method, path, headers=headers or {})
    r = c.getresponse()
    body = r.read()
    hdrs = dict(r.getheaders())
    status = r.status
    c.close()
    return status, body, hdrs


def test_auth_required_without_token():
    srv, port = _mk_auth_server()
    try:
        assert _req(port)[0] == 401
    finally:
        srv.stop()


def test_auth_bearer_and_custom_header():
    srv, port = _mk_auth_server()
    try:
        assert _req(port, headers={"Authorization": "Bearer secret"})[0] == 200
        assert _req(port, headers={"X-Wuxing-Token": "secret"})[0] == 200
        assert _req(port, headers={"Authorization": "Bearer wrong"})[0] == 401
    finally:
        srv.stop()


def test_query_token_exchanges_cookie():
    srv, port = _mk_auth_server()
    try:
        status, _b, h = _req(port, "GET", "/ping?token=secret")
        assert status == 302
        assert h["Location"] == "/ping"
        set_cookie = h["Set-Cookie"]
        assert "HttpOnly" in set_cookie and "SameSite=Lax" in set_cookie
        assert SESSION_COOKIE in set_cookie
        # cookie 复访
        status2, _b2, _h2 = _req(
            port, headers={"Cookie": f"{SESSION_COOKIE}=secret"})
        assert status2 == 200
        # 查询参数保留、token 剔除
        _s, _b3, h3 = _req(port, "GET", "/ping?x=1&token=secret")
        assert h3["Location"] == "/ping?x=1"
    finally:
        srv.stop()


def test_query_token_wrong_rejected():
    srv, port = _mk_auth_server()
    try:
        status, _b, h = _req(port, "GET", "/ping?token=wrong")
        assert status == 401 and "Set-Cookie" not in h
    finally:
        srv.stop()


def test_query_token_not_exchanged_for_mutating():
    srv, port = _mk_auth_server()
    try:
        status, _b, _h = _req(port, "POST", "/ping?token=secret",
                              headers={"X-Wuxing": "1",
                                       "Content-Type": "application/json"})
        assert status == 401
    finally:
        srv.stop()


def test_rate_limit_blocks_even_valid_token():
    srv, port = _mk_auth_server()
    try:
        for _ in range(10):
            status, _b, _h = _req(
                port, headers={"Authorization": "Bearer wrong"})
            assert status == 401
        status, _b, h = _req(
            port, headers={"Authorization": "Bearer secret"})
        assert status == 429
        assert h.get("Retry-After")
        assert _req(port)[0] == 429
    finally:
        srv.stop()


def test_health_and_options_exempt_from_auth():
    srv, port = _mk_auth_server()
    try:
        assert _req(port, "GET", "/health")[0] == 200
        assert _req(port, "OPTIONS", "/ping")[0] == 204
    finally:
        srv.stop()


def test_token_never_in_logs(caplog):
    srv, port = _mk_auth_server(token="TopSecret99")
    try:
        with caplog.at_level(logging.INFO, logger="wuxing.shell.auth"):
            _req(port, headers={"Authorization": "Bearer TopSecret99-fail"})
            _req(port, "GET", "/ping?token=TopSecret99")
        assert "TopSecret99" not in caplog.text
        assert "TopSecret99" not in "".join(
            r.getMessage() for r in caplog.records)
    finally:
        srv.stop()


def test_allow_lists_extras_and_denials():
    srv, port = _mk_auth_server(
        allow_hosts=["100.64.1.5"],
        allow_origins=["https://wuxing.example.com"])
    try:
        # 白名单 Host（+ 白名单 Origin）
        status, _b, _h = _req(port, headers={
            "Host": "100.64.1.5:8723",
            "Origin": "https://wuxing.example.com",
            "Authorization": "Bearer secret",
        })
        assert status == 200
        # 环回默认仍放行
        assert _req(port, headers={"Authorization": "Bearer secret"})[0] == 200
        # 越界 Host → 403
        assert _req(port, headers={"Host": "192.168.1.9:8723",
                                   "Authorization": "Bearer secret"})[0] == 403
        # 越界 Origin → 403
        assert _req(port, headers={"Origin": "http://evil.example",
                                   "Authorization": "Bearer secret"})[0] == 403
    finally:
        srv.stop()


def test_bind_host_auto_allowed():
    from wuxing.shell.web.server import ShellServer
    srv = ShellServer(host="192.168.1.5", port=0)
    assert srv.host_allowed("192.168.1.5")
    srv2 = ShellServer(host="0.0.0.0", port=0)
    assert not srv2.host_allowed("0.0.0.0")
    assert srv2.host_allowed("127.0.0.60")  # 环回默认集不变


def test_default_mode_unchanged_without_guard():
    from wuxing.shell.web.hub import EventHub
    from wuxing.shell.web.server import ShellServer

    def ping(req):
        return {"pong": True}

    srv = ShellServer(port=0, hub=EventHub())
    srv.add_route("GET", "^/ping$", ping)
    srv.add_route("POST", "^/ping$", ping)
    port = srv.start()
    try:
        assert _req(port)[0] == 200                       # 无票也放行（默认）
        assert _req(port, "POST", "/ping",
                    headers={"X-Wuxing": "1"})[0] == 200
        assert _req(port, "POST", "/ping")[0] == 403      # 变更头纪律不变
    finally:
        srv.stop()
