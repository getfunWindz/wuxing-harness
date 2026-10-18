"""TDD · O2-2 P1：浏览器三工具 + 通道客户端（降级/授权/落盘）。

设计：docs/WUXING_内置浏览器体验断言_设计_2026-10-07.md §3/§4。
"""
import pathlib

from wuxing import browser_identity
from wuxing.config import EngineConfig
from wuxing.tools import browser_tool as bt
from wuxing.tools.loader import load_tools
from wuxing.workspace import Workspace


class FakeClient:
    def __init__(self, responses=None):
        self.calls = []
        self.responses = responses or {}

    def call(self, cmd, timeout=None, **args):
        self.calls.append((cmd, dict(args)))
        resp = self.responses.get(cmd, {})
        if isinstance(resp, Exception):
            raise resp
        return resp


def _split_identity(call):
    """（cmd, args）→ 弹出 identity 后的 (cmd, args)；缺身份=失败（机制纪律）。"""
    cmd, args = call
    ident = args.pop("identity", None)
    assert isinstance(ident, dict), f"{cmd} 未携带 identity"
    assert ident["key"].startswith("wuxing-browser-")
    assert ident["mode"] in ("memory", "persist")
    assert ident["workspace"]
    return cmd, args


def _ws(tmp_path):
    return Workspace(tmp_path)


def _nav(tmp_path, cfg=None, client=None, guard=None):
    return bt.BrowserNavigateTool(
        _ws(tmp_path), cfg or EngineConfig(), client=client,
        guard_check=guard, resolve_private=lambda host: False)


def test_no_channel_loud_degradation(tmp_path, monkeypatch):
    monkeypatch.setattr(bt, "_default_client", lambda: None)
    t = bt.BrowserNavigateTool(
        _ws(tmp_path), EngineConfig(browser_domains_allow=["example.com"]))
    res = t.execute(url="https://example.com")
    assert res.status == "error"
    assert "仅桌面壳可用" in res.error


def test_public_requires_explicit_allow(tmp_path):
    t = _nav(tmp_path, client=FakeClient())
    res = t.execute(url="https://example.com")
    assert res.status == "error" and "domain not allowed" in res.error


def test_public_allowed_passes_table(tmp_path):
    cfg = EngineConfig(browser_domains_allow=["example.com"])
    client = FakeClient({"open": {"title": "T", "url": "https://example.com/"}})
    t = _nav(tmp_path, cfg=cfg, client=client)
    res = t.execute(url="https://example.com")
    assert res.status == "ok" and "T" in res.content
    assert _split_identity(client.calls[0]) == ("open", {"url": "https://example.com"})


def test_deny_wins_over_allow(tmp_path):
    cfg = EngineConfig(browser_domains_allow=["example.com"],
                       browser_domains_deny=["example.com"])
    t = _nav(tmp_path, cfg=cfg, client=FakeClient())
    res = t.execute(url="https://example.com")
    assert res.status == "error"


def test_private_hard_denied(tmp_path):
    t = _nav(tmp_path, client=FakeClient())
    res = t.execute(url="http://192.168.1.10:8000")
    assert res.status == "error" and "私网" in res.error


def test_dns_private_fail_closed(tmp_path):
    t = bt.BrowserNavigateTool(
        _ws(tmp_path), EngineConfig(browser_domains_allow=["internal.corp"]),
        client=FakeClient(), resolve_private=lambda host: True)
    res = t.execute(url="http://internal.corp")
    assert res.status == "error" and "私网" in res.error


def test_scheme_rejected(tmp_path):
    t = _nav(tmp_path, client=FakeClient())
    res = t.execute(url="file:///etc/passwd")
    assert res.status == "error"


def test_loopback_guard_allowed(tmp_path):
    from wuxing.browser_guard import GuardDecision
    client = FakeClient({"open": {"title": "Dev", "url": "http://127.0.0.1:3000/"}})
    calls = []

    def guard(host, port, **kw):
        calls.append((host, port, kw))
        return GuardDecision(kind="allowed", address=f"{host}:{port}")

    t = _nav(tmp_path, client=client, guard=guard)
    res = t.execute(url="http://127.0.0.1:3000")
    assert res.status == "ok"
    assert calls and calls[0][1] == 3000
    assert _split_identity(client.calls[0]) == ("open", {"url": "http://127.0.0.1:3000"})


def test_loopback_no_listener(tmp_path):
    from wuxing.browser_guard import GuardDecision
    t = _nav(tmp_path, guard=lambda h, p, **kw: GuardDecision(
        kind="no_listener", address=f"{h}:{p}"))
    res = t.execute(url="http://127.0.0.1:3999")
    assert res.status == "error" and "无应用监听" in res.error


def test_loopback_confirm_pending(tmp_path):
    from wuxing.browser_guard import GuardDecision, Occupant
    occ = Occupant(pid=1, exe="x.exe", cmdline="x", label="x.exe")
    t = _nav(tmp_path, guard=lambda h, p, **kw: GuardDecision(
        kind="confirm_required", address=f"{h}:{p}", occupant=occ,
        pending_id="p1"))
    res = t.execute(url="http://127.0.0.1:3000", reason="核查体验")
    assert res.status == "needs_answer"
    assert res.pending_questions
    assert "127.0.0.1:3000" in res.pending_questions[0]["title"]
    assert res.pending_meta["kind"] == "browser_access"
    assert res.pending_meta["pending_id"] == "p1"


def test_snapshot_truncates_and_persists(tmp_path):
    big = "- button \"x\" [ref=e1]\n" * 600
    client = FakeClient({"snapshot": {"snapshot": big, "refs": 1,
                                      "truncated": False, "total": 600}})
    t = bt.BrowserSnapshotTool(_ws(tmp_path), client=client)
    res = t.execute()
    assert res.status == "ok" and "已截断" in res.content
    files = list((tmp_path / ".wuxing" / "browser" / "default"
                  / "snapshots").glob("*.txt"))
    assert files and files[0].read_text(encoding="utf-8") == big


def test_snapshot_short_passthrough(tmp_path):
    client = FakeClient({"snapshot": {"snapshot": '- button "ok" [ref=e1]',
                                      "refs": 1}})
    t = bt.BrowserSnapshotTool(_ws(tmp_path), client=client)
    res = t.execute()
    assert "已截断" not in res.content and "refs=1" in res.content


def test_screenshot_copies_into_workspace(tmp_path):
    import tempfile
    tmp_png = pathlib.Path(tempfile.mkdtemp()) / "shot.png"
    tmp_png.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    client = FakeClient({"screenshot": {"path": str(tmp_png), "full_page": False}})
    t = bt.BrowserScreenshotTool(_ws(tmp_path), client=client)
    res = t.execute()
    assert res.status == "ok"
    assert ".wuxing/browser/default/screenshots/" in res.content
    files = list((tmp_path / ".wuxing" / "browser" / "default"
                  / "screenshots").glob("*.png"))
    assert files and files[0].read_bytes().startswith(b"\x89PNG")
    assert not tmp_png.exists()


def test_screenshot_path_traversal_rejected(tmp_path):
    client = FakeClient({"screenshot": {"path": "x.png"}})
    t = bt.BrowserScreenshotTool(_ws(tmp_path), client=client)
    res = t.execute(path="../evil.png")
    assert res.status == "error"


def test_permissions_declared(tmp_path):
    t = bt.BrowserNavigateTool(_ws(tmp_path), EngineConfig())
    assert t.permission() == {"read": True, "write": False, "execute": True,
                              "network": True, "destructive": False}
    assert bt.BrowserSnapshotTool(_ws(tmp_path)).permission()["write"] is False
    assert bt.BrowserScreenshotTool(_ws(tmp_path)).permission()["write"] is True


def test_loader_conditional_registration(tmp_path):
    ws = _ws(tmp_path)
    names = {t.name() for t in load_tools(ws).list()}
    assert "browser_navigate" not in names
    tools = [bt.BrowserNavigateTool(ws, EngineConfig()),
             bt.BrowserSnapshotTool(ws), bt.BrowserScreenshotTool(ws)]
    names2 = {t.name() for t in load_tools(ws, browser=tools).list()}
    assert {"browser_navigate", "browser_snapshot",
            "browser_screenshot"} <= names2


def test_engine_registers_browser_tools_when_enabled(tmp_path):
    """O2-2 P1 T7 / P2：引擎装配——默认关不注册；启用才注册六工具。"""
    from wuxing.engine import Engine
    off = Engine(cfg=EngineConfig(llm="mock"), workdir=tmp_path / "off")
    assert off.tools.get("browser_navigate") is None
    on = Engine(cfg=EngineConfig(llm="mock", browser_enabled=True),
                workdir=tmp_path / "on")
    names = {t.name() for t in on.tools.list()}
    assert {"browser_navigate", "browser_snapshot", "browser_screenshot",
            "browser_click", "browser_type", "browser_wait"} <= names


# ---- O2-2 P2：click/type/wait 三工具 ----


def test_p2_click_validation_and_call(tmp_path):
    client = FakeClient({"click": {"clicked": True, "by": "ref=e1"}})
    t = bt.BrowserClickTool(_ws(tmp_path), client=client)
    res = t.execute(ref="e1")
    assert res.status == "ok" and "已点击" in res.content
    assert _split_identity(client.calls[0]) == ("click", {"ref": "e1"})
    assert t.execute().status == "error"
    assert t.execute(ref="e1", selector="#a").status == "error"
    res2 = t.execute(selector="#a")
    assert res2.status == "ok"
    assert _split_identity(client.calls[-1]) == ("click", {"selector": "#a"})


def test_p2_type_validation_and_call(tmp_path):
    client = FakeClient({"type": {"typed": True, "chars": 2}})
    t = bt.BrowserTypeTool(_ws(tmp_path), client=client)
    res = t.execute(ref="e1", text="中文", submit=True)
    assert res.status == "ok"
    assert _split_identity(client.calls[0]) == (
        "type", {"ref": "e1", "text": "中文", "submit": True})
    assert t.execute(ref="e1", text="").status == "error"
    assert t.execute(text="x").status == "error"
    assert t.execute(ref="e1", text="x", submit="yes").status == "error"
    assert t.execute(ref="e1").status == "error"  # text 缺失


def test_p2_wait_validation_and_call(tmp_path):
    client = FakeClient({"wait": {"found": True, "mode": "selector",
                                  "elapsed_ms": 3}})
    t = bt.BrowserWaitTool(_ws(tmp_path), client=client)
    res = t.execute(selector="#done", timeout_ms=1000)
    assert res.status == "ok"
    assert _split_identity(client.calls[0]) == (
        "wait", {"selector": "#done", "timeout_ms": 1000})
    assert t.execute().status == "error"
    assert t.execute(selector="#a", ms=100).status == "error"
    assert t.execute(ms=0).status == "error"
    assert t.execute(ms=60001).status == "error"
    assert t.execute(timeout_ms=5).status == "error"  # 无条件
    res2 = t.execute(text="完成")
    assert res2.status == "ok"


def test_p2_permissions_declared(tmp_path):
    for t in (bt.BrowserClickTool(_ws(tmp_path)),
              bt.BrowserTypeTool(_ws(tmp_path)),
              bt.BrowserWaitTool(_ws(tmp_path))):
        assert t.permission() == {"read": True, "write": False,
                                  "execute": True, "network": True,
                                  "destructive": False}


# ---- O2-2 P3：evaluate 显式档 ----


def test_p3_evaluate_validation_and_call(tmp_path):
    client = FakeClient({"evaluate": {"value": "42", "exception": None}})
    t = bt.BrowserEvaluateTool(_ws(tmp_path), client=client)
    res = t.execute(expression="6*7")
    assert res.status == "ok" and "42" in res.content
    assert _split_identity(client.calls[0]) == ("evaluate", {"expression": "6*7"})
    assert t.execute(expression="").status == "error"
    assert t.execute(expression="   ").status == "error"
    assert t.execute().status == "error"
    assert t.execute(expression="x" * 4001).status == "error"


def test_p3_evaluate_exception_fail_visible(tmp_path):
    client = FakeClient({"evaluate": {"value": None,
                                       "exception": "SyntaxError: boom"}})
    t = bt.BrowserEvaluateTool(_ws(tmp_path), client=client)
    res = t.execute(expression="(")
    assert res.status == "error" and "SyntaxError" in res.error


def test_p3_evaluate_truncates_and_dumps(tmp_path):
    big = "y" * 9000
    client = FakeClient({"evaluate": {"value": big, "exception": None}})
    t = bt.BrowserEvaluateTool(_ws(tmp_path), client=client)
    res = t.execute(expression="big")
    assert res.status == "ok"
    assert "落盘" in res.content
    files = list((pathlib.Path(tmp_path) / ".wuxing" / "browser"
                  / "default" / "evaluates").glob("*.txt"))
    assert files and files[0].read_text(encoding="utf-8") == big


def test_p3_engine_evaluate_gating(tmp_path):
    """双闸：browser_enabled 与 browser_evaluate_enabled 双开才注册。"""
    from wuxing.engine import Engine
    on_only = Engine(cfg=EngineConfig(llm="mock", browser_enabled=True),
                     workdir=tmp_path / "on-only")
    assert on_only.tools.get("browser_evaluate") is None
    both = Engine(cfg=EngineConfig(llm="mock", browser_enabled=True,
                                   browser_evaluate_enabled=True),
                  workdir=tmp_path / "both")
    assert both.tools.get("browser_evaluate") is not None
    names = {t.name() for t in both.tools.list()}
    assert {"browser_navigate", "browser_click"} <= names


# ---- O2-2 §11.5-①：工具面携带身份 ----


def test_tools_attach_identity_mode_from_cfg(tmp_path):
    """persist 档：命令携带 mode=persist（配置驱动）。"""
    cfg = EngineConfig(browser_domains_allow=["example.com"])
    cfg.browser_identity_mode = "persist"
    client = FakeClient({"open": {"title": "T", "url": "https://example.com/"}})
    t = _nav(tmp_path, cfg=cfg, client=client)
    t.execute(url="https://example.com")
    cmd, args = client.calls[0]
    assert cmd == "open" and args["identity"]["mode"] == "persist"


def test_snapshot_attaches_identity(tmp_path):
    client = FakeClient({"snapshot": {"snapshot": "x"}})
    t = bt.BrowserSnapshotTool(_ws(tmp_path), EngineConfig(), client=client)
    t.execute()
    assert client.calls[0][1]["identity"]["mode"] == "memory"


def test_navigate_emits_identity_trace(tmp_path):
    logged = []

    class _Trace:
        def log(self, event, unit, domain, **fields):
            logged.append((event, fields))

    cfg = EngineConfig(browser_domains_allow=["example.com"])
    client = FakeClient({"open": {"title": "T", "url": "https://example.com/",
                                  "identity": {"key": "wuxing-browser-x",
                                               "mode": "memory",
                                               "state": "created"}}})
    t = bt.BrowserNavigateTool(_ws(tmp_path), cfg, client=client,
                               resolve_private=lambda host: False,
                               trace_getter=lambda: _Trace())
    t.execute(url="https://example.com")
    assert any(e[0] == "browser_identity_used" and e[1].get("key")
               for e in logged)


# ---- O2-2 §11.5-②：会话绑定 + 落盘按 run（Q1=B/D5） ----


def test_identity_session_overlay_via_binding(tmp_path):
    """binding.session → memory 键 = 基键 + 会话 overlay。"""
    client = FakeClient({"snapshot": {"snapshot": "x"}})
    t = bt.BrowserSnapshotTool(_ws(tmp_path), EngineConfig(), client=client,
                               binding={"session": "sess-a"})
    t.execute()
    ident = client.calls[0][1]["identity"]
    base = browser_identity.identity_key(tmp_path)
    assert ident["key"].startswith(base + "-")
    assert ident["key"] != base
    assert ident["mode"] == "memory"


def test_identity_anchor_manifest_root(tmp_path):
    """D1：worktree run（manifest_root=主工作区）→ 基键锚定真实工作区。"""
    class _Ws:
        root = tmp_path / "wt"
        manifest_root = tmp_path / "main"

    client = FakeClient({"snapshot": {"snapshot": "x"}})
    t = bt.BrowserSnapshotTool(_Ws(), EngineConfig(), client=client)
    t.execute()
    ident = client.calls[0][1]["identity"]
    assert ident["key"] == browser_identity.identity_key(tmp_path / "main")
    assert ident["workspace"] == str(tmp_path / "main")


def test_persist_binding_ignores_session(tmp_path):
    cfg = EngineConfig()
    cfg.browser_identity_mode = "persist"
    client = FakeClient({"snapshot": {"snapshot": "x"}})
    t = bt.BrowserSnapshotTool(_ws(tmp_path), cfg, client=client,
                               binding={"session": "sess-a"})
    t.execute()
    ident = client.calls[0][1]["identity"]
    assert ident["key"] == browser_identity.identity_key(tmp_path)


def test_artifact_dirs_scoped_by_run(tmp_path):
    big = "- button \"x\" [ref=e1]\n" * 600
    client = FakeClient({"snapshot": {"snapshot": big, "refs": 1,
                                      "total": 600}})
    t = bt.BrowserSnapshotTool(_ws(tmp_path), client=client,
                               binding={"run": "run-abc"})
    res = t.execute()
    assert res.status == "ok"
    files = list((tmp_path / ".wuxing" / "browser" / "run-abc"
                  / "snapshots").glob("*.txt"))
    assert files and files[0].read_text(encoding="utf-8") == big


def test_evaluate_dump_scoped_by_run(tmp_path):
    big = "y" * 9000
    client = FakeClient({"evaluate": {"value": big, "exception": None}})
    t = bt.BrowserEvaluateTool(_ws(tmp_path), client=client,
                               binding={"run": "run-abc"})
    res = t.execute(expression="big")
    assert res.status == "ok" and "run-abc" in res.content
    files = list((tmp_path / ".wuxing" / "browser" / "run-abc"
                  / "evaluates").glob("*.txt"))
    assert files and files[0].read_text(encoding="utf-8") == big


def test_screenshot_default_scoped_by_run(tmp_path):
    import tempfile
    tmp_png = pathlib.Path(tempfile.mkdtemp()) / "shot.png"
    tmp_png.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    client = FakeClient({"screenshot": {"path": str(tmp_png)}})
    t = bt.BrowserScreenshotTool(_ws(tmp_path), client=client,
                                 binding={"run": "run-abc"})
    res = t.execute()
    assert res.status == "ok"
    assert ".wuxing/browser/run-abc/screenshots/" in res.content
    files = list((tmp_path / ".wuxing" / "browser" / "run-abc"
                  / "screenshots").glob("*.png"))
    assert files and files[0].read_bytes().startswith(b"\x89PNG")


def test_engine_browser_binding_from_preset_session(tmp_path, monkeypatch):
    """引擎装配：preset_session → 工具命令身份带会话 overlay。"""
    from wuxing.engine import Engine
    client = FakeClient({"snapshot": {"snapshot": "x"}})
    monkeypatch.setattr(bt, "_default_client", lambda: client)
    eng = Engine(cfg=EngineConfig(llm="mock", browser_enabled=True),
                 workdir=tmp_path / "eng", preset_session="sess-a")
    tool = eng.tools.get("browser_snapshot")
    assert tool is not None
    tool.execute()
    ident = client.calls[0][1]["identity"]
    base = browser_identity.identity_key(tmp_path / "eng")
    assert ident["key"].startswith(base + "-")


# ---- O2-2 §11.5-③：导航 LAN 接线 + storage-state 透传（Q1=A/D2/D10） ----


def _lan_decision(kind, **kw):
    from wuxing.browser_guard import GuardDecision
    defaults = {"address": "192.168.1.10:8000", "source": "lan"}
    defaults.update(kw)
    return GuardDecision(kind=kind, **defaults)


def test_navigate_lan_requires_allowlist(tmp_path):
    """白名单外私网 IP → loud 拒（不出通道）。"""
    cfg = EngineConfig(browser_lan_allow=["192.168.1.0/24"])
    client = FakeClient()
    t = _nav(tmp_path, cfg=cfg, client=client)
    res = t.execute(url="http://192.168.9.9/")
    assert res.status == "error" and "白名单" in res.error
    assert client.calls == []


def test_navigate_lan_confirm_pending(tmp_path):
    cfg = EngineConfig(browser_lan_allow=["192.168.1.0/24"])
    t = _nav(tmp_path, cfg=cfg, client=FakeClient())
    t._lan_check = lambda host, port, **kw: _lan_decision(
        "confirm_required", pending_id="p1")
    res = t.execute(url="http://192.168.1.10:8000/", reason="内网核查")
    assert res.status == "needs_answer"
    assert res.pending_meta["guard_kind"] == "lan"
    assert "局域网" in res.pending_questions[0]["title"]


def test_navigate_lan_allowed_proceeds(tmp_path):
    from wuxing.browser_guard import GuardDecision
    cfg = EngineConfig(browser_lan_allow=["192.168.1.0/24"])
    client = FakeClient({"open": {"title": "NAS",
                                  "url": "http://192.168.1.10:8000/"}})
    t = _nav(tmp_path, cfg=cfg, client=client)
    t._lan_check = lambda host, port, **kw: GuardDecision(
        kind="allowed", address="192.168.1.10:8000", source="lan")
    res = t.execute(url="http://192.168.1.10:8000/")
    assert res.status == "ok" and "NAS" in res.content
    assert client.calls and client.calls[0][0] == "open"


def test_navigate_lan_name_resolves_private(tmp_path):
    """D2：名称解析落私网 → 走 LAN 路径（允许名单内则确认/放行）。"""
    calls = []
    cfg = EngineConfig(browser_lan_allow=["192.168.1.0/24"])
    t = _nav(tmp_path, cfg=cfg, client=FakeClient())
    t._resolve_private = lambda host: True   # 名称解析落私网（fail-closed 语义）

    def lan(host, port, **kw):
        calls.append((host, port, kw.get("lan_allow")))
        return _lan_decision("lan_denied", note="地址不在 browser_lan_allow 白名单")

    t._lan_check = lan
    res = t.execute(url="http://nas.local:8080/")
    assert res.status == "error" and "白名单" in res.error
    assert calls and calls[0][0] == "nas.local" and calls[0][2] == ["192.168.1.0/24"]


def test_navigate_storage_state_passes_state_path(tmp_path):
    state = tmp_path / "s.json"
    state.write_text('{"cookies": [{"name": "a", "value": "b", '
                     '"domain": "example.com", "path": "/"}], '
                     '"origins": []}', encoding="utf-8")
    cfg = EngineConfig(browser_domains_allow=["example.com"])
    cfg.browser_identity_mode = "storage-state"
    cfg.browser_storage_state_path = str(state)
    logged = []

    class _Trace:
        def log(self, event, unit, domain, **fields):
            logged.append((event, fields))

    client = FakeClient({"open": {
        "title": "T", "url": "https://example.com/",
        "identity": {"key": "k", "mode": "storage-state",
                     "state": "created"},
        "storage_state": {"cookies": 1, "origins": 0}}})
    t = bt.BrowserNavigateTool(_ws(tmp_path), cfg, client=client,
                               resolve_private=lambda host: False,
                               trace_getter=lambda: _Trace())
    res = t.execute(url="https://example.com")
    assert res.status == "ok"
    ident = client.calls[0][1]["identity"]
    assert ident["state_path"] == str(state)
    ev = [e for e in logged if e[0] == "browser_storage_state_loaded"]
    assert ev and ev[0][1]["cookies"] == 1 and ev[0][1]["origins"] == 0
    assert "value" not in str(ev[0][1])   # 值纪律


def test_navigate_storage_state_invalid_loud(tmp_path):
    cfg = EngineConfig(browser_domains_allow=["example.com"])
    cfg.browser_identity_mode = "storage-state"
    cfg.browser_storage_state_path = ""
    t = _nav(tmp_path, cfg=cfg, client=FakeClient())
    res = t.execute(url="https://example.com")
    assert res.status == "error" and "storage-state" in res.error


def test_snapshot_storage_state_invalid_loud(tmp_path):
    cfg = EngineConfig()
    cfg.browser_identity_mode = "storage-state"
    cfg.browser_storage_state_path = str(tmp_path / "missing.json")
    t = bt.BrowserSnapshotTool(_ws(tmp_path), cfg, client=FakeClient())
    res = t.execute()
    assert res.status == "error" and "storage-state" in res.error
