"""E2-5 排期池 A5：web_fetch（配置面 / 工具 / 装载集成）。

计划：docs/plans/2026-10-03-wuxing-web-fetch.md（T1-T5）。
纪律：默认关、未启用不注册、私网硬拒（fetch 时解析复检）、SEC1/G6 联动；离线测试（mock 网络）。
"""
import pathlib

from wuxing.config import EngineConfig
from wuxing.config_schema import FIELD_SPECS
from wuxing.tools.web_tool import MAX_OUTPUT_CHARS, WebFetchTool
from wuxing.workspace import Workspace

# ---------------- T1：配置面 ----------------

def test_web_fetch_defaults_off():
    cfg = EngineConfig()
    assert cfg.web_fetch_enabled is False
    assert tuple(cfg.web_fetch_domains_allow) == ()
    assert tuple(cfg.web_fetch_domains_deny) == ()


def test_web_fetch_in_schema():
    names = {s.name for s in FIELD_SPECS}
    assert {"web_fetch_enabled", "web_fetch_domains_allow",
            "web_fetch_domains_deny"} <= names


# ---------------- T3：工具实现（mock 网络——离线） ----------------

def _mk_tool(tmp_path, **cfg_kw):
    cfg = EngineConfig(web_fetch_enabled=True, **cfg_kw)
    ws = Workspace(pathlib.Path(tmp_path))
    return WebFetchTool(ws, cfg), ws


def test_disabled_tool_refuses(tmp_path):
    """防御纵深：即使被调用，未启用一律拒绝。"""
    cfg = EngineConfig()  # 默认关
    tool = WebFetchTool(Workspace(pathlib.Path(tmp_path)), cfg)
    res = tool.execute(url="https://example.com/")
    assert res.status == "error" and "policy:" in res.error


def test_fetch_html_to_text(monkeypatch, tmp_path):
    """HTML → 正文文本；script/style 去除；实体解码。"""
    tool, _ws = _mk_tool(tmp_path)
    import wuxing.tools.web_tool as wt
    monkeypatch.setattr(wt, "resolve_private", lambda host: False)
    monkeypatch.setattr(
        wt, "_http_get",
        lambda url, timeout: (200, "text/html; charset=utf-8",
                              b"<html><script>x()</script><p>Hello &amp; hi</p></html>",
                              ""))
    res = tool.execute(url="https://example.com/page")
    assert res.status == "ok", res.error
    assert "Hello & hi" in res.content
    assert "x()" not in res.content, "script 内容必须剔除"


def test_fetch_private_denied(monkeypatch, tmp_path):
    """私网地址 → status=error + policy: 前缀；不得发起请求。"""
    tool, _ws = _mk_tool(tmp_path)
    import wuxing.tools.web_tool as wt
    calls = {"n": 0}

    def _boom(*a, **k):
        calls["n"] += 1
        return (200, "text/html", b"x", "")

    monkeypatch.setattr(wt, "_http_get", _boom)
    res = tool.execute(url="http://127.0.0.1/admin")
    assert res.status == "error" and "policy:" in res.error
    assert calls["n"] == 0, "拒绝必须发生在请求之前"


def test_domain_deny_and_allow(monkeypatch, tmp_path):
    tool, _ws = _mk_tool(tmp_path, web_fetch_domains_deny=["evil.com"])
    res = tool.execute(url="https://a.evil.com/x")
    assert res.status == "error" and "policy:" in res.error
    tool2, _ws2 = _mk_tool(tmp_path / "r2", web_fetch_domains_allow=["python.org"])
    res2 = tool2.execute(url="https://example.com/x")
    assert res2.status == "error" and "policy:" in res2.error


def test_redirect_hop_rechecked(monkeypatch, tmp_path):
    """302 → 目标私网 → policy 拒绝（逐跳复检，不追发）。"""
    tool, _ws = _mk_tool(tmp_path)
    import wuxing.tools.web_tool as wt
    monkeypatch.setattr(wt, "resolve_private", lambda host: False)
    calls = []

    def fake_get(url, timeout):
        calls.append(url)
        return (302, "text/html", b"", "http://127.0.0.1/steal")

    monkeypatch.setattr(wt, "_http_get", fake_get)
    res = tool.execute(url="https://example.com/start")
    assert res.status == "error" and "policy:" in res.error
    assert len(calls) == 1, "重定向目标被拒后不得继续追发"


def test_timeout_and_http_error_classified(monkeypatch, tmp_path):
    tool, _ws = _mk_tool(tmp_path)
    import wuxing.tools.web_tool as wt
    monkeypatch.setattr(wt, "resolve_private", lambda host: False)

    def _timeout(url, timeout):
        raise TimeoutError("timed out")

    monkeypatch.setattr(wt, "_http_get", _timeout)
    res = tool.execute(url="https://example.com/x")
    assert res.status == "error" and res.error.startswith("fetch:")
    monkeypatch.setattr(wt, "_http_get",
                        lambda url, timeout: (404, "text/html", b"nope", ""))
    res2 = tool.execute(url="https://example.com/x")
    assert res2.status == "error" and "404" in res2.error


def test_unsupported_content_type(monkeypatch, tmp_path):
    tool, _ws = _mk_tool(tmp_path)
    import wuxing.tools.web_tool as wt
    monkeypatch.setattr(wt, "resolve_private", lambda host: False)
    monkeypatch.setattr(wt, "_http_get",
                        lambda url, timeout: (200, "application/octet-stream",
                                              b"\x00\x01", ""))
    res = tool.execute(url="https://example.com/bin")
    assert res.status == "error" and "content-type" in res.error


def test_oversize_truncated_with_spill(monkeypatch, tmp_path):
    """正文超上限 → 截断 + G6 落盘（.wuxing/truncated 有全文）。"""
    tool, ws = _mk_tool(tmp_path)
    import wuxing.tools.web_tool as wt
    monkeypatch.setattr(wt, "resolve_private", lambda host: False)
    big = ("<p>" + "字" * (MAX_OUTPUT_CHARS + 50) + "</p>").encode("utf-8")
    monkeypatch.setattr(wt, "_http_get",
                        lambda url, timeout: (200, "text/html", big, ""))
    res = tool.execute(url="https://example.com/big")
    assert res.status == "ok"
    assert "截断" in res.content
    spill = list((ws.root / ".wuxing" / "truncated").glob("*.txt"))
    assert spill, "超限必须走 G6 落盘"


def test_max_chars_parameter_clamped(monkeypatch, tmp_path):
    tool, _ws = _mk_tool(tmp_path)
    import wuxing.tools.web_tool as wt
    monkeypatch.setattr(wt, "resolve_private", lambda host: False)
    body = ("x" * 5000).encode("utf-8")
    monkeypatch.setattr(wt, "_http_get",
                        lambda url, timeout: (200, "text/plain", body, ""))
    res = tool.execute(url="https://example.com/x", max_chars=100)
    assert res.status == "ok" and "截断" in res.content


# ---------------- T4：装载 / 白名单 / 剖面集成 ----------------

def test_disabled_not_registered(tmp_path):
    """未启用 → 注册表无 web_fetch。"""
    from wuxing.tools.loader import load_tools
    ws = Workspace(pathlib.Path(tmp_path))
    reg = load_tools(ws)
    assert reg.get("web_fetch") is None


def test_enabled_registered_and_whitelisted(tmp_path):
    """启用 → 注册存在；plan/execute/design 白名单可达、verify/user 不可达。"""
    from wuxing.domains.defaults import DEFAULT_DOMAINS, DESIGN_DOMAIN
    from wuxing.tools.loader import load_tools
    ws = Workspace(pathlib.Path(tmp_path))
    tool = WebFetchTool(ws, EngineConfig(web_fetch_enabled=True))
    reg = load_tools(ws, web_fetch=tool)
    assert reg.get("web_fetch") is not None
    assert "web_fetch" in DEFAULT_DOMAINS["plan"].tool_whitelist
    assert "web_fetch" in DEFAULT_DOMAINS["execute"].tool_whitelist
    assert "web_fetch" in DESIGN_DOMAIN.tool_whitelist
    assert "web_fetch" not in DEFAULT_DOMAINS["verify"].tool_whitelist
    assert "web_fetch" not in DEFAULT_DOMAINS["user"].tool_whitelist


def test_read_only_profile_excludes_web_fetch(tmp_path):
    """SEC3 read-only 剖面移除 web_fetch（network 类）。"""
    from wuxing.permissions import filter_registry
    from wuxing.tools.base import ToolRegistry
    ws = Workspace(pathlib.Path(tmp_path))
    tool = WebFetchTool(ws, EngineConfig(web_fetch_enabled=True))
    reg = ToolRegistry([tool])
    removed = filter_registry(reg, "read-only")
    assert "web_fetch" in removed
    assert reg.get("web_fetch") is None


def test_engine_assembly_conditional_registration(tmp_path):
    """Engine 装配点条件注册（启用→注册；默认→不注册——含 delegate 子装配同源）。"""
    from wuxing.engine import Engine
    eng = Engine(EngineConfig(web_fetch_enabled=True, llm="mock"),
                 workdir=pathlib.Path(tmp_path))
    assert eng.tools.get("web_fetch") is not None
    eng2 = Engine(EngineConfig(llm="mock"), workdir=pathlib.Path(tmp_path / "b"))
    assert eng2.tools.get("web_fetch") is None
