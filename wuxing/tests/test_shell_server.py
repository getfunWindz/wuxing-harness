"""TDD：HTTP 服务与本地安全（壳 P1 · B2）。

设计 §4.1/§4.3：stdlib ThreadingHTTPServer；路由 + JSON 错误契约；
本地安全三件套——Origin/Host 校验 + 变更请求自定义头（强制预检）+
静态路径逃逸防护。
"""
import http.client
import json
import pathlib
import tempfile


def _start(**kw):
    from wuxing.shell.web.server import ShellServer
    srv = ShellServer(port=0, **kw)
    port = srv.start()
    return srv, port


def _request(port, method, path, body=None, headers=None):
    c = http.client.HTTPConnection("127.0.0.60", port, timeout=5)
    c.request(method, path, body=body, headers=headers or {})
    r = c.getresponse()
    data = r.read()
    status, hdrs = r.status, dict(r.getheaders())
    c.close()
    return status, hdrs, data


def test_health_ok_and_epoch():
    from wuxing.shell.web.hub import EventHub
    hub = EventHub()
    srv, port = _start(hub=hub)
    try:
        status, _hdrs, data = _request(port, "GET", "/health")
        assert status == 200, data
        payload = json.loads(data)
        assert payload["status"] == "ok"
        assert payload["epoch"] == hub.epoch
        assert isinstance(payload["pid"], int)
        from wuxing.shell.web.version import SHELL_VERSION
        assert payload["version"] == SHELL_VERSION
    finally:
        srv.stop()


def test_unknown_path_404_json_error():
    srv, port = _start()
    try:
        status, _hdrs, data = _request(port, "GET", "/nope")
        assert status == 404
        payload = json.loads(data)
        assert payload["error"]["code"] == "not_found"
        assert "message" in payload["error"]
    finally:
        srv.stop()


def test_mutating_requires_custom_header():
    srv, port = _start()
    try:
        status, _, _ = _request(port, "POST", "/api/v1/anything", body="{}")
        assert status == 403, "变更请求缺 X-Wuxing 头必须拒绝"
        status, _, _ = _request(port, "POST", "/api/v1/anything", body="{}",
                                headers={"X-Wuxing": "1",
                                         "Content-Type": "application/json"})
        assert status == 404, "带头后进入路由（路径不存在 → 404）"
    finally:
        srv.stop()


def test_cross_origin_rejected_allowed_origin_ok():
    srv, port = _start()
    try:
        status, _, _ = _request(port, "GET", "/health",
                                headers={"Origin": "http://evil.example"})
        assert status == 403, "跨源必须拒绝"
        status, _, _ = _request(
            port, "GET", "/health",
            headers={"Origin": f"http://127.0.0.60:{port}"})
        assert status == 200, "本机同源必须放行"
    finally:
        srv.stop()


def test_static_serving_and_path_escape_blocked():
    static = pathlib.Path(tempfile.mkdtemp())
    # P2-M8：新壳产物布局 static/next/——根路径仅作 /next/ 入口（302）
    (static / "next").mkdir()
    (static / "next" / "index.html").write_text("<h1>wuxing</h1>",
                                                encoding="utf-8")
    outside = static.parent / "secret.txt"
    outside.write_text("TOP-SECRET", encoding="utf-8")
    srv, port = _start(static_dir=static)
    try:
        status, hdrs, data = _request(port, "GET", "/")
        assert status == 302 and hdrs.get("Location") == "/next/"
        status, hdrs, data = _request(port, "GET", "/next/")
        assert status == 200 and b"wuxing" in data
        assert "text/html" in hdrs.get("Content-Type", "")
        for evil in ("/../secret.txt", "/..%2Fsecret.txt",
                     "/%2e%2e/secret.txt"):
            status, _, data = _request(port, "GET", evil)
            assert status in (403, 404), f"{evil} 必须被拒绝（实际 {status}）"
            assert b"TOP-SECRET" not in data, f"{evil} 不得泄漏目录外内容"
    finally:
        srv.stop()


def test_route_registration():
    from wuxing.shell.web.server import json_response
    srv, port = _start()
    srv.add_route("GET", r"^/api/v1/ping$",
                  lambda req: json_response({"pong": True}))
    try:
        status, _, data = _request(port, "GET", "/api/v1/ping")
        assert status == 200 and json.loads(data)["pong"] is True
    finally:
        srv.stop()


def test_server_start_skips_fqdn_reverse_lookup(monkeypatch):
    """启动路径不得调用 socket.getfqdn（HTTPServer.server_bind 的 PTR 反查会阻塞 ~5s）。"""
    import socket
    calls = []
    monkeypatch.setattr(socket, "getfqdn", lambda h: calls.append(h) or h)
    srv, _port = _start()
    try:
        assert calls == [], "启动路径不得调用 socket.getfqdn（反向 DNS 反查）"
    finally:
        srv.stop()
