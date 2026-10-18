"""E3-3（X6）：ToolSearch 延迟加载——配置/判定/检索/披露。"""
import pathlib

from wuxing.protocols import ToolResult
from wuxing.tools.base import Tool, ToolRegistry
from wuxing.workspace import Workspace


class _FakeMcp(Tool):
    def __init__(self, server, tool, desc="", schema=None):
        self._server, self._tool, self._desc = server, tool, desc
        self._schema = schema or {"type": "object", "properties": {}}
        self.is_mcp = True

    def name(self):
        from wuxing.tools.mcp_bridge import mcp_tool_name
        return mcp_tool_name(self._server, self._tool)

    def description(self):
        return self._desc

    def input_schema(self):
        return self._schema

    def permission(self):
        return {"read": True, "write": False, "execute": False,
                "network": False, "destructive": False}

    def execute(self, **kw):
        return ToolResult(status="ok", content="x", tool_name=self.name())


class _Named(Tool):
    def __init__(self, name, desc=""):
        self._n, self._d = name, desc

    def name(self):
        return self._n

    def description(self):
        return self._d

    def input_schema(self):
        return {"type": "object", "properties": {}, "required": []}

    def permission(self):
        return {"read": True, "write": False, "execute": False,
                "network": False, "destructive": False}

    def execute(self, **kw):
        return ToolResult(status="ok", content="x", tool_name=self._n)


def _load(monkeypatch, tmp_path, servers=("srv",), n=3, **kw):
    """经 loader.load_tools 装载（monkeypatch MCP 连接为假工具）。"""
    from wuxing.tools import loader as L
    fakes = []
    for srv in servers:
        fakes += [_FakeMcp(srv, f"t{i}", desc=f"{srv} 工具{i}")
                  for i in range(n)]

    async def _fake_load(configs, pool=None):
        return fakes

    monkeypatch.setattr(L, "load_mcp_tools", _fake_load)
    ws = Workspace(pathlib.Path(tmp_path))
    reg = L.load_tools(ws, L.ToolLoaderConfig(mcp_servers=["x"]), **kw)
    return reg, fakes


# ---------------- 配置面（双写） ----------------

def test_config_defaults_and_schema():
    from wuxing.config import EngineConfig
    from wuxing.config_schema import FIELD_SPECS
    cfg = EngineConfig()
    assert cfg.tool_search_enabled is True
    assert cfg.tool_search_threshold == 20
    assert tuple(cfg.mcp_always_load) == ()
    names = {s.name for s in FIELD_SPECS}
    assert {"tool_search_enabled", "tool_search_threshold",
            "mcp_always_load"} <= names


# ---------------- loader 判定 ----------------

def test_defer_when_threshold_exceeded(monkeypatch, tmp_path):
    reg, fakes = _load(monkeypatch, tmp_path, n=3, tool_search_threshold=2)
    assert all(getattr(f, "deferred", False) for f in fakes)
    assert reg.get("tool_search") is not None


def test_below_threshold_no_defer(monkeypatch, tmp_path):
    reg, fakes = _load(monkeypatch, tmp_path, n=2, tool_search_threshold=20)
    assert not any(getattr(f, "deferred", False) for f in fakes)
    assert reg.get("tool_search") is None


def test_disabled_zero_behavior(monkeypatch, tmp_path):
    reg, fakes = _load(monkeypatch, tmp_path, n=3, tool_search_threshold=2,
                       tool_search_enabled=False)
    assert not any(getattr(f, "deferred", False) for f in fakes)
    assert reg.get("tool_search") is None


def test_no_mcp_zero_behavior(tmp_path):
    from wuxing.tools import loader as L
    ws = Workspace(pathlib.Path(tmp_path))
    reg = L.load_tools(ws, L.ToolLoaderConfig())
    assert reg.get("tool_search") is None


def test_always_load_server_exempt(monkeypatch, tmp_path):
    reg, fakes = _load(monkeypatch, tmp_path, servers=("a", "b"), n=2,
                       tool_search_threshold=2, mcp_always_load=("a",))
    a = [f for f in fakes if f._server == "a"]
    b = [f for f in fakes if f._server == "b"]
    assert not any(getattr(f, "deferred", False) for f in a)
    assert all(getattr(f, "deferred", False) for f in b)
    assert reg.get("tool_search") is not None


# ---------------- 提示词披露 ----------------

def test_prompt_hides_deferred_and_hints():
    from wuxing.domains.defaults import DEFAULT_DOMAINS
    from wuxing.prompt_builder import system_sections
    d = _FakeMcp("srv", "hidden", desc="隐藏的")
    d.deferred = True
    wl = [d, _Named("tool_search", "检索")]
    secs = system_sections(DEFAULT_DOMAINS["execute"], wl, True, 5)
    text = next(s["text"] for s in secs if s["name"] == "tools")
    assert "mcp__srv__hidden" not in text
    assert "tool_search" in text and "延迟加载" in text
    secs2 = system_sections(DEFAULT_DOMAINS["execute"], wl, True, 5)
    assert text == next(s["text"] for s in secs2 if s["name"] == "tools")


def test_prompt_no_hint_without_tool_search():
    from wuxing.domains.defaults import DEFAULT_DOMAINS
    from wuxing.prompt_builder import system_sections
    d = _FakeMcp("srv", "hidden", desc="隐藏的")
    d.deferred = True
    secs = system_sections(DEFAULT_DOMAINS["execute"], [d], True, 5)
    text = next(s["text"] for s in secs if s["name"] == "tools")
    assert "延迟加载" not in text


# ---------------- tool_search 工具 ----------------

def test_tool_search_matches_and_orders():
    from wuxing.tools.tool_search import ToolSearchTool
    a = _FakeMcp("srv", "query_db", "查询数据库内容")
    b = _FakeMcp("srv", "send_mail", "发送邮件")
    for f in (a, b):
        f.deferred = True
    res = ToolSearchTool(ToolRegistry([a, b])).execute(query="数据库")
    assert res.status == "ok"
    assert "mcp__srv__query_db" in res.content
    _idx = res.content.find("mcp__srv__send_mail")
    assert _idx == -1 or res.content.index("mcp__srv__query_db") < _idx


def test_tool_search_name_hit_beats_description():
    from wuxing.tools.tool_search import ToolSearchTool
    a = _FakeMcp("srv", "deploy", "别的说明")
    b = _FakeMcp("srv", "other", "关于 deploy 的说明")
    for f in (a, b):
        f.deferred = True
    res = ToolSearchTool(ToolRegistry([a, b])).execute(query="deploy")
    assert res.content.index("mcp__srv__deploy") < res.content.index(
        "mcp__srv__other")


def test_tool_search_empty_query_lists_by_name():
    from wuxing.tools.tool_search import ToolSearchTool
    a = _FakeMcp("srv", "bbb", "B")
    b = _FakeMcp("srv", "aaa", "A")
    for f in (a, b):
        f.deferred = True
    res = ToolSearchTool(ToolRegistry([a, b])).execute(query="")
    assert res.content.index("mcp__srv__aaa") < res.content.index("mcp__srv__bbb")


def test_tool_search_limit_clamped():
    from wuxing.tools.tool_search import ToolSearchTool
    fakes = [_FakeMcp("srv", f"t{i}", "x") for i in range(5)]
    for f in fakes:
        f.deferred = True
    t = ToolSearchTool(ToolRegistry(fakes))
    assert t.execute(query="", limit=1).content.count("mcp__srv__") == 1
    assert t.execute(query="", limit=999).content.count("mcp__srv__") == 5


def test_tool_search_truncates_description():
    from wuxing.tools.tool_search import ToolSearchTool
    f = _FakeMcp("srv", "big", "长" * 3000)
    f.deferred = True
    res = ToolSearchTool(ToolRegistry([f])).execute(query="big")
    assert res.content.count("长") <= 2048


def test_tool_search_excludes_non_deferred():
    from wuxing.tools.tool_search import ToolSearchTool
    a = _FakeMcp("srv", "visible", "可见")
    b = _FakeMcp("srv", "hidden", "隐藏")
    b.deferred = True
    res = ToolSearchTool(ToolRegistry([a, b])).execute(query="")
    assert "mcp__srv__hidden" in res.content
    assert "mcp__srv__visible" not in res.content


def test_tool_search_includes_schema():
    from wuxing.tools.tool_search import ToolSearchTool
    f = _FakeMcp("srv", "t", "d", schema={"type": "object",
                                           "properties": {"q": {"type": "string"}}})
    f.deferred = True
    res = ToolSearchTool(ToolRegistry([f])).execute(query="t")
    assert "\"q\"" in res.content


# ---------------- 白名单 ----------------

def test_whitelist_contains_tool_search():
    from wuxing.domains.defaults import DEFAULT_DOMAINS
    for dom in ("plan", "execute", "verify", "user"):
        assert "tool_search" in DEFAULT_DOMAINS[dom].tool_whitelist, dom
