"""HTTP 服务（壳 P1 · B2）——stdlib ThreadingHTTPServer + 路由 + 本地安全 + 远程鉴权。

设计 §4.1/§4.3（O5 安全门 T1/T2 扩展）：
  - 默认仅绑 127.0.0.60（环回别名——避让 DeepSeek harness 的 127.0.0.1）；
    **远程档（O5）**：非环回绑定由 launcher 强制装配 AuthGuard（fail-closed）；
  - **Host/Origin 校验**（环回默认 + 白名单扩展——见 shell_allow_hosts/origins）；
  - **远程鉴权**：Bearer / X-Wuxing-Token 头 或会话 cookie（?token= 首次换发）；
    `/health` 与 OPTIONS 豁免；失败按 IP 限速（429）；
  - **变更类请求要求自定义头 `X-Wuxing: 1`**（强制 CORS 预检——阻断简单跨源请求）；
  - **静态托管限定 static_dir 内**（路径逃逸拒绝）；JSON 错误契约统一
    `{error: {code, message}}`。
"""
import http.server
import json as _json
import logging
import mimetypes
import os
import pathlib
import re
import socketserver
import threading
import urllib.parse

from .auth import (
    SESSION_COOKIE,
    cookie_token,
    token_from_headers,
)
from .auth import (
    logger as auth_logger,
)
from .version import SHELL_VERSION

logger = logging.getLogger(__name__)

_JSON_CT = "application/json; charset=utf-8"
_MUTATING = {"POST", "PUT", "PATCH", "DELETE"}

# 默认绑定地址：环回别名（DeepSeek harness 占用 127.0.0.1——用户裁决 2026-09-13）
DEFAULT_HOST = "127.0.0.60"
# 环回默认放行的 Host 集（白名单扩展之外，默认行为不变的基线）
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", DEFAULT_HOST, "localhost", "::1"})


class Request:
    """请求视图（路由处理器入参）。"""

    __slots__ = ("body", "headers", "method", "params", "path", "query")

    def __init__(self, method, path, query, headers, body):
        self.method = method
        self.path = path
        self.query = query          # dict[str, str]
        self.headers = headers
        self.body = body            # bytes
        self.params = {}            # 路由命名组

    def json(self):
        if not self.body:
            raise ValueError("empty body")
        return _json.loads(self.body.decode("utf-8"))

    def header(self, name, default=""):
        return self.headers.get(name, default)


class Response:
    """响应（路由处理器返回）。"""

    __slots__ = ("body", "content_type", "headers", "status")

    def __init__(self, status=200, body=b"", content_type=_JSON_CT,
                 headers=None):
        self.status = status
        self.body = (body if isinstance(body, bytes)
                     else str(body).encode("utf-8"))
        self.content_type = content_type
        self.headers = dict(headers or {})


class StreamResponse:
    """流式响应（SSE 等）——chunks 为生成器（str/bytes）；连接以 close 收尾。"""

    __slots__ = ("chunks", "content_type", "headers")

    def __init__(self, chunks, content_type="text/event-stream",
                 headers=None):
        self.chunks = chunks
        self.content_type = content_type
        self.headers = dict(headers or {})


def json_response(payload, status=200, headers=None) -> Response:
    return Response(status,
                    _json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                    _JSON_CT, headers)


def error_response(status, code, message, headers=None) -> Response:
    return json_response({"error": {"code": code, "message": message}}, status,
                         headers)


def _serve_static(root: pathlib.Path, url_path: str):
    """静态文件（限定 root 内；越界 → 403；不存在 → None）。"""
    rel = url_path.lstrip("/") or "index.html"
    try:
        root_resolved = root.resolve()
        target = (root / rel).resolve()
        if not target.is_relative_to(root_resolved):
            return error_response(403, "forbidden", "路径逃逸")
    except (OSError, ValueError):
        # 路径解析失败（坏字符/越界前盾）→ None（调用方按 404 处理）
        return None
    if target.is_dir():
        target = target / "index.html"
    if not target.is_file():
        return None
    ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
    if ctype.startswith("text/") or ctype in (
            "application/javascript", "application/json"):
        ctype += "; charset=utf-8"
    try:
        data = target.read_bytes()
    except OSError:
        # 静态文件读取失败（如竞态删除）→ None（调用方按 404 处理）
        return None
    return Response(200, data, ctype)


class _HTTPServer(http.server.ThreadingHTTPServer):
    """本地服务 HTTP 服务器——跳过 server_bind 的 getfqdn 反查。

    stdlib HTTPServer.server_bind 会对绑定地址做反向 DNS（socket.getfqdn）；
    127.0.0.60 在 Windows 上无 PTR 记录，每次启动阻塞 ~5s（实测 4.97s）。
    server_name 仅 CGI 场景使用，本服务不用——直接取 host。
    """

    def server_bind(self):
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = host
        self.server_port = port


class _Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "wuxing-shell"
    sys_version = ""
    _pending_cookie = ""

    def log_message(self, fmt, *args):
        pass  # 静默（可观测走 EventHub/trace，不打 stderr）

    # ---- 本地安全与远程鉴权 ----
    def _host_ok(self) -> bool:
        host = self.headers.get("Host", "")
        if not host:
            return False
        hostname = host.rsplit(":", 1)[0].strip("[]").lower()
        return self.server.host_allowed(hostname)

    def _auth_check(self, path: str, query: dict) -> str:
        """鉴权判定：ok / query_ok（?token= 换发）/ limited / denied。

        guard 存在即强制（不按客户端 IP 豁免）；/health 与 OPTIONS 豁免
        （存活探活与 CORS 预检不携带凭证）。
        """
        guard = getattr(self.server, "auth", None)
        if guard is None or self.command == "OPTIONS" or path == "/health":
            return "ok"
        ip = self.client_address[0]
        if guard.is_rate_limited(ip):
            return "limited"
        value = token_from_headers(self.headers)
        if value is None:
            value = cookie_token(self.headers.get("Cookie", ""))
        if guard.verify(value):
            return "ok"
        qtok = query.get("token")
        if qtok and self.command in ("GET", "HEAD") and guard.verify(qtok):
            self._pending_cookie = qtok
            return "query_ok"
        guard.note_failure(ip)
        return "denied"

    def _cookie_redirect(self, parsed, query) -> Response:
        """?token= 首次换发：302 回原路径（剔除 token）+ HttpOnly 会话 cookie。"""
        rest = urllib.parse.urlencode(
            [(k, v) for k, v in query.items() if k != "token"])
        location = parsed.path + (f"?{rest}" if rest else "")
        cookie = (f"{SESSION_COOKIE}={self._pending_cookie}; HttpOnly; "
                  "SameSite=Lax; Path=/; Max-Age=2592000")
        auth_logger.info("auth.cookie_issued ip=%s path=%s",
                         self.client_address[0], parsed.path)
        return Response(302, b"", "text/plain; charset=utf-8",
                        headers={"Location": location, "Set-Cookie": cookie,
                                 "Cache-Control": "no-store"})

    def _read_body(self) -> bytes:
        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
        except ValueError:
            length = 0
        return self.rfile.read(length) if length > 0 else b""

    def _send(self, resp: Response) -> None:
        body = resp.body or b""
        self.send_response(resp.status)
        for k, v in resp.headers.items():
            self.send_header(k, v)
        self.send_header("Content-Type", resp.content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD" and body:
            self.wfile.write(body)

    def _send_stream(self, resp: StreamResponse) -> None:
        """流式写出（SSE）：无 Content-Length、Connection: close，逐块 flush。"""
        self.send_response(200)
        self.send_header("Content-Type", resp.content_type)
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        for k, v in resp.headers.items():
            self.send_header(k, v)
        self.end_headers()
        self.close_connection = True
        try:
            for chunk in resp.chunks:
                if isinstance(chunk, str):
                    chunk = chunk.encode("utf-8")
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError) as exc:
            logger.debug("客户端断开（正常收尾）：%s", exc)
        except Exception as exc:
            logger.debug("流内异常（不拖垮服务线程）：%s", exc)

    # ---- 分发 ----
    def _dispatch(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        path = urllib.parse.unquote(parsed.path)
        query = {k: v[0] for k, v in
                 urllib.parse.parse_qs(parsed.query).items()}
        # 本地安全：Host（环回默认 + 白名单扩展）
        if not self._host_ok():
            hostname = self.headers.get("Host", "").rsplit(":", 1)[0]
            logger.warning("host 拒绝：%s（见 shell_allow_hosts）", hostname)
            self._send(error_response(403, "forbidden", "本地安全校验失败"))
            return
        # Origin（环回派生 + 白名单扩展）
        origin = self.headers.get("Origin")
        if origin and origin not in self.server.allowed_origins():
            self._send(error_response(403, "forbidden", "来源校验失败"))
            return
        # 远程鉴权（guard 存在即强制；/health 与 OPTIONS 豁免）
        auth_state = self._auth_check(path, query)
        if auth_state == "query_ok":
            self._send(self._cookie_redirect(parsed, query))
            return
        if auth_state == "limited":
            retry_after = str(int(self.server.auth.window_s))
            self._send(error_response(429, "rate_limited",
                                      "失败次数过多，请稍后再试",
                                      headers={"Retry-After": retry_after}))
            return
        if auth_state == "denied":
            auth_logger.warning("auth.denied ip=%s path=%s",
                                self.client_address[0], path)
            self._send(error_response(401, "unauthorized", "需要访问令牌"))
            return
        # 变更类请求要求自定义头（强制 CORS 预检——阻断简单跨源请求）
        if self.command in _MUTATING and self.headers.get("X-Wuxing") != "1":
            self._send(error_response(403, "forbidden", "本地安全校验失败"))
            return
        if self.command == "OPTIONS":
            self._send(Response(204, b"", "text/plain; charset=utf-8",
                                self.server.cors_headers(
                                    self.headers.get("Origin"))))
            return
        req = Request(self.command, path, query, self.headers,
                      self._read_body())
        for method, pattern, fn in self.server.routes:
            if method != self.command:
                continue
            m = pattern.match(path)
            if not m:
                continue
            req.params = m.groupdict()
            try:
                resp = fn(req)
            except Exception as exc:  # 路由异常 → 500（不泄漏堆栈）
                resp = error_response(500, "internal", type(exc).__name__)
            if isinstance(resp, StreamResponse):
                self._send_stream(resp)
                return
            if not isinstance(resp, Response):
                resp = json_response(resp)
            self._send(resp)
            return
        static = self.server.static_dir
        if static is not None and self.command in ("GET", "HEAD"):
            # P2-M8：根路径直达新壳（旧栈删除——/ 仅作 /next/ 入口）
            if path in ("/", "/index.html"):
                self._send(Response(302, b"", "text/html; charset=utf-8",
                                    headers={"Location": "/next/"}))
                return
            resp = _serve_static(static, path)
            if resp is not None:
                self._send(resp)
                return
        self._send(error_response(404, "not_found",
                                  f"{self.command} {path}"))

    do_GET = _dispatch
    do_POST = _dispatch
    do_DELETE = _dispatch
    do_PUT = _dispatch
    do_PATCH = _dispatch
    do_OPTIONS = _dispatch
    do_HEAD = _dispatch


class ShellServer:
    """本地服务（线程模型与引擎一致；默认仅本机）。"""

    def __init__(self, host: str = DEFAULT_HOST, port: int = 0,
                 static_dir=None, hub=None, *, auth=None,
                 allow_hosts=None, allow_origins=None):
        self.host = host
        self.port = int(port)
        self.static_dir = pathlib.Path(static_dir) if static_dir else None
        self.hub = hub
        self.auth = auth
        self.allow_hosts = set(allow_hosts or [])
        self.allow_origins = set(allow_origins or [])
        bind = (host or "").strip().strip("[]").lower()
        if bind and bind not in ("0.0.0.0", "::"):
            # 具体绑定位自动纳入白名单（显式选择的一致性；通配 0.0.0.0/:: 不代填）
            self.allow_hosts.add(bind)
        self.routes = [("GET", re.compile(r"^/health$"), self._health)]
        self._httpd = None
        self._thread = None
        self._port = None

    def add_route(self, method: str, pattern: str, fn) -> None:
        self.routes.append((method.upper(), re.compile(pattern), fn))

    def start(self) -> int:
        """启动服务（返回实际端口）。幂等保护：已启动则直接返回。"""
        if self._httpd is not None:
            return self._port
        self._httpd = _HTTPServer((self.host, self.port), _Handler)
        self._httpd.routes = self.routes
        self._httpd.static_dir = self.static_dir
        self._httpd.hub = self.hub
        self._httpd.allowed_origins = self.allowed_origins
        self._httpd.cors_headers = self.cors_headers
        self._httpd.host_allowed = self.host_allowed
        self._httpd.auth = self.auth
        self._port = self._httpd.server_address[1]
        self._thread = threading.Thread(
            target=self._httpd.serve_forever,
            kwargs={"poll_interval": 0.2}, daemon=True)
        self._thread.start()
        return self._port

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self._port or self.port}"

    def host_allowed(self, hostname: str) -> bool:
        """Host 校验：环回默认集 + 显式白名单扩展。"""
        return hostname in _LOOPBACK_HOSTS or hostname in self.allow_hosts

    def allowed_origins(self) -> set:
        p = self._port or self.port
        origins = {f"http://{self.host}:{p}",
                   f"http://{DEFAULT_HOST}:{p}",
                   f"http://127.0.0.1:{p}",
                   f"http://localhost:{p}"}
        for h in self.allow_hosts:
            origins.add(f"http://{h}:{p}")
        origins.update(self.allow_origins)
        return origins

    @staticmethod
    def cors_headers(origin=None) -> dict:
        return {"Access-Control-Allow-Origin": origin or "",
                "Access-Control-Allow-Headers":
                    "X-Wuxing, X-Wuxing-Token, Authorization, Content-Type",
                "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS"}

    def _health(self, req) -> Response:
        return json_response({"status": "ok", "version": SHELL_VERSION,
                              "pid": os.getpid(),
                              "epoch": getattr(self.hub, "epoch", None)})
