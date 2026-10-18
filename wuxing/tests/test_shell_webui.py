"""壳服务静态托管与界面纪律守卫（P2-M8 后：旧栈已删除）。

范围：
  - 根路径直达新壳（/ → 302 /next/）；/next/ 构建产物托管（部署后）；
  - 界面纪律：静态资源（HTML/CSS/JS）全局禁止 emoji（设计 §8）。

新壳前端的其余守卫由 TS 侧承担（apps/shell：typecheck + 架构红线 + node 单测）。
"""
import http.client
import pathlib
import re
import socket

import pytest

STATIC = pathlib.Path(__file__).resolve().parents[1] / "shell" / "web" / "static"

# 界面纪律（设计 §8）：静态资源全局禁止 emoji
_EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F2FF]")


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.60", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_root_redirects_to_next():
    """P2-M8：根路径直达新壳（旧栈删除——/ 仅作 /next/ 入口）。"""
    from wuxing.shell.web.server import ShellServer
    srv = ShellServer(port=0, static_dir=STATIC)
    port = srv.start()
    try:
        c = http.client.HTTPConnection("127.0.0.60", port, timeout=5)
        c.request("GET", "/")
        r = c.getresponse()
        r.read()
        c.close()
        assert r.status == 302, r.status
        assert r.headers.get("Location") == "/next/", r.headers.get("Location")
    finally:
        srv.stop()


def test_next_bundle_served_when_present():
    """新壳构建产物托管（部署后）：/next/ → HTML；CI 无构建 → skip。"""
    if not (STATIC / "next" / "index.html").is_file():
        pytest.skip("新壳构建产物未部署（CI 无 npm build）")
    from wuxing.shell.web.server import ShellServer
    srv = ShellServer(port=0, static_dir=STATIC)
    port = srv.start()
    try:
        c = http.client.HTTPConnection("127.0.0.60", port, timeout=5)
        c.request("GET", "/next/")
        r = c.getresponse()
        body = r.read()
        c.close()
        assert r.status == 200, r.status
        assert b"<html" in body.lower()
        assert "text/html" in r.headers.get("Content-Type", "")
    finally:
        srv.stop()


def test_launcher_serves_static_dir(tmp_path):
    """launcher 构造的服务必须托管前端目录（根路径 → 新壳入口）。"""
    from wuxing.shell.web import launcher
    port = _free_port()
    mgr, srv = launcher.ensure_service(
        port=port, state_path_override=tmp_path / "ws.json")
    try:
        c = http.client.HTTPConnection("127.0.0.60", port, timeout=5)
        c.request("GET", "/")
        r = c.getresponse()
        r.read()
        c.close()
        assert r.status == 302 and r.headers.get("Location") == "/next/"
    finally:
        srv.stop()
        mgr.shutdown()


def test_static_has_no_emoji():
    """界面纪律：静态资源（HTML/CSS/JS）全局禁止 emoji（设计 §8）。

    旧栈删除后扫描面 = 新壳构建产物（static/next）；CI 无构建 → 自然通过。
    """
    bad = []
    for p in STATIC.rglob("*"):
        if p.suffix in (".html", ".css", ".js"):
            hit = _EMOJI_RE.search(p.read_text(encoding="utf-8"))
            if hit:
                bad.append(f"{p.relative_to(STATIC)}:{hit.group(0)}")
    assert not bad, bad
