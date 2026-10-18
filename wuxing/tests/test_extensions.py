"""E0-A 扩展机制单测/集成测（设计 2026-09-26 §5 测试策略）。"""
import pathlib
import textwrap


def _write_ext(dirpath: pathlib.Path, name: str, body: str) -> pathlib.Path:
    """在 dirpath 写一个扩展模块文件（测试夹具）。"""
    dirpath.mkdir(parents=True, exist_ok=True)
    p = dirpath / f"{name}.py"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return p


def test_extension_config_defaults_and_schema():
    """D2：默认开启、附加目录缺省空；config.py 与 FIELD_SPECS 双写。"""
    from wuxing.config import EngineConfig
    from wuxing.config_schema import FIELD_SPECS
    cfg = EngineConfig()
    assert cfg.extension_enabled is True
    assert cfg.extension_dirs == []
    spec = {s.name: s for s in FIELD_SPECS}
    assert spec["extension_enabled"].type == "bool"
    assert spec["extension_enabled"].default is True
    assert spec["extension_dirs"].type == "list"
    assert spec["extension_dirs"].default == []


def test_extension_tool_normalizes_execute_results():
    """execute 归一（设计 §2.2）：str/dict → ok；ToolResult 透传；异常 → error。"""
    from wuxing.extensions import ExtensionTool
    from wuxing.protocols import ToolResult

    def _ok(**kw): return kw.get("text", "")
    t = ExtensionTool(name="ext_echo", description="d", parameters={},
                      execute=_ok)
    r = t.execute(text="hi")
    assert r.status == "ok" and r.content == "hi" and r.tool_name == "ext_echo"

    t2 = ExtensionTool(name="ext_obj", description="d", parameters={},
                       execute=lambda **kw: {"n": 1})
    assert t2.execute().content == '{"n": 1}'

    t3 = ExtensionTool(name="ext_tr", description="d", parameters={},
                       execute=lambda **kw: ToolResult(status="ok", content="x"))
    assert t3.execute().status == "ok" and t3.execute().content == "x"

    def _boom(**kw):
        raise ValueError("bad")
    t4 = ExtensionTool(name="ext_boom", description="d", parameters={},
                       execute=_boom)
    r4 = t4.execute()
    assert r4.status == "error" and "ValueError" in r4.error


def test_extension_tool_permission_default_conservative():
    """缺省全禁（设计 §2.2）：未显式声明 → 全 False（Registry 默认拒绝执行）。"""
    from wuxing.extensions import ExtensionTool
    t = ExtensionTool(name="ext_p", description="d", parameters={},
                      execute=lambda **kw: "x")
    assert t.permission() == {"read": False, "write": False, "execute": False,
                              "network": False, "destructive": False}
    t2 = ExtensionTool(name="ext_p2", description="d", parameters={},
                       execute=lambda **kw: "x", permission={"read": True})
    assert t2.permission() == {"read": True}
    assert t2.is_extension is True


def test_dispatcher_order_isolation_and_zero_behavior():
    """分发顺序（扩展先、原 on_event 后）；异常隔离；无钩子零行为。"""
    from wuxing.events import UnitStarted
    from wuxing.extensions import EventDispatcher
    d = EventDispatcher()
    seen = []
    d.add("UnitStarted", lambda ev: seen.append("ext"))

    def _boom(ev):
        raise RuntimeError("boom")

    d.add("UnitStarted", _boom)
    forwarded = []
    wrapped = d.wrap(lambda ev: forwarded.append("orig"))
    wrapped(UnitStarted(unit_id="F-1", domain_id="execute"))
    assert seen == ["ext"]
    assert forwarded == ["orig"]  # 钩子异常不阻断原 on_event
    # 幂等：已包装不再叠加
    assert d.wrap(wrapped) is wrapped
    # 无钩子：原样返回（零行为）
    empty = EventDispatcher()
    fn = lambda ev: None
    assert empty.wrap(fn) is fn


def test_dispatcher_hook_error_trace(tmp_path):
    """钩子异常 → trace extension_hook_error（可见）。"""
    from wuxing.events import UnitStarted
    from wuxing.extensions import EventDispatcher
    from wuxing.trace import TraceLogger
    trace = TraceLogger(tmp_path / "trace.jsonl")
    d = EventDispatcher(trace=trace)

    def _boom(ev):
        raise RuntimeError("bad hook")
    d.add("UnitStarted", _boom, source="audit")
    d.wrap(None)(UnitStarted(unit_id="F-1", domain_id="execute"))
    rows = trace.load()
    assert any(r["event"] == "extension_hook_error"
               and r.get("name") == "audit"
               and r.get("event_name") == "UnitStarted" for r in rows)


def test_load_extensions_zero_behavior(tmp_path):
    """目录不存在 = 零行为（设计 §4 末行）。"""
    from wuxing.extensions import load_extensions
    res = load_extensions(tmp_path)
    assert res.loaded == [] and res.tools == [] and res.problems == []
    assert res.summary_note() == ""
    assert res.dispatcher.has_hooks() is False


def test_load_extensions_loaded_and_broken_classified(tmp_path):
    """导入失败 / 无 register → broken（带原因，不阻断其余加载）。"""
    from wuxing.extensions import load_extensions
    d = tmp_path / "ext"
    _write_ext(d, "good", """
        def register(api):
            api.on("UnitStarted", lambda ev: None)
    """)
    _write_ext(d, "broken_import", "import not_a_real_module_xyz\n")
    _write_ext(d, "no_register", "X = 1\n")
    res = load_extensions(tmp_path, dirs=[d])
    assert [r.name for r in res.loaded] == ["good"]
    assert len(res.problems) == 2
    assert any("broken_import" in p for p in res.problems)
    assert any("no_register" in p for p in res.problems)
    assert res.dispatcher.has_hooks() is True
    assert res.summary_note().startswith("[扩展] 2 个加载失败：")


def test_load_extensions_disabled(tmp_path):
    """显式关闭 → 完全不加载（D2）。"""
    from wuxing.extensions import load_extensions
    d = tmp_path / "ext"
    _write_ext(d, "good", """
        def register(api):
            api.on("UnitStarted", lambda ev: None)
    """)
    res = load_extensions(tmp_path, enabled=False, dirs=[d])
    assert res.loaded == [] and res.problems == []
    assert res.dispatcher.has_hooks() is False


def test_load_extensions_register_error_is_transactional(tmp_path):
    """register 中途抛错 → 该扩展零生效（暂存区不提交）+ 问题登记。"""
    from wuxing.extensions import load_extensions
    d = tmp_path / "ext"
    _write_ext(d, "partial", """
        def register(api):
            api.register_tool(name="ext_partial", description="d",
                              parameters={}, execute=lambda **kw: "x",
                              permission={"read": True})
            api.on("UnitStarted", lambda ev: None)
            raise RuntimeError("late failure")
    """)
    res = load_extensions(tmp_path, dirs=[d])
    assert res.tools == []
    assert res.dispatcher.has_hooks() is False
    assert any("partial" in p and "注册失败" in p for p in res.problems)


def test_load_extensions_registers_tool_and_domain_merge(tmp_path):
    """工具注册可见 + domains 合并（对应域可见、其他域不可见）。"""
    from wuxing.extensions import load_extensions
    from wuxing.tools.base import ToolRegistry
    reg = ToolRegistry([])
    d = tmp_path / "ext"
    _write_ext(d, "counter", """
        def register(api):
            api.register_tool(
                name="ext_count",
                description="统计行数",
                parameters={"type": "object",
                            "properties": {"path": {"type": "string"}}},
                execute=lambda path="": {"path": path, "lines": 1},
                domains=("execute",),
                permission={"read": True})
    """)
    res = load_extensions(tmp_path, dirs=[d], registry=reg)
    assert [t.name() for t in res.tools] == ["ext_count"]
    assert reg.get("ext_count") is not None
    in_exec = [t.name() for t in reg.filter(("read_file",), domain_id="execute")]
    assert in_exec == ["ext_count"]
    assert reg.filter(("read_file",), domain_id="verify") == []
    assert reg.filter(("read_file",)) == []  # 无域上下文不合并


def test_load_extensions_tool_conflict_rejected_visible(tmp_path):
    """同名工具冲突：先加载者胜、后加载者拒绝 + 问题登记（设计 §2.1/§4）。"""
    from wuxing.extensions import load_extensions
    from wuxing.tools.base import ToolRegistry
    reg = ToolRegistry([])
    d = tmp_path / "ext"
    for mod in ("a_first", "b_second"):
        _write_ext(d, mod, f"""
            def register(api):
                api.register_tool(name="ext_dup", description="{mod}",
                                  parameters={{}}, execute=lambda **kw: "{mod}",
                                  permission={{"read": True}})
        """)
    res = load_extensions(tmp_path, dirs=[d], registry=reg)
    assert [t.name() for t in res.tools] == ["ext_dup"]
    assert reg.get("ext_dup").description() == "a_first"
    assert any("b_second" in p and "冲突" in p for p in res.problems)


def test_resolve_extension_dirs_order_and_relative(tmp_path, monkeypatch):
    """目录顺序：用户级 → 项目级 → 附加（相对路径按工作区解析）。"""
    import wuxing.extensions as ext
    user = tmp_path / "user_ext"
    monkeypatch.setattr(ext, "user_extensions_dir", lambda: user)
    dirs = ext.resolve_extension_dirs(tmp_path, ["extra", str(tmp_path / "abs")])
    assert dirs == [user, tmp_path / ".wuxing" / "extensions",
                    tmp_path / "extra", tmp_path / "abs"]


def test_load_extensions_user_then_project_order(tmp_path, monkeypatch):
    """双目录顺序：用户级先、项目级后（同名冲突 → 项目级拒绝）。"""
    import wuxing.extensions as ext
    user = tmp_path / "user_ext"
    proj = tmp_path / ".wuxing" / "extensions"
    monkeypatch.setattr(ext, "user_extensions_dir", lambda: user)
    for d, tag in ((user, "user"), (proj, "proj")):
        _write_ext(d, "same", f"""
            def register(api):
                api.register_tool(name="ext_same", description="{tag}",
                                  parameters={{}}, execute=lambda **kw: "{tag}",
                                  permission={{"read": True}})
        """)
    res = ext.load_extensions(tmp_path)
    assert res.tools[0].description() == "user"
    assert any("冲突" in p for p in res.problems)


def test_load_extensions_trace_events(tmp_path):
    """可见性：成功 → extension_loaded；失败 → extension_error（设计 §2.1）。"""
    from wuxing.extensions import load_extensions
    from wuxing.trace import TraceLogger
    trace = TraceLogger(tmp_path / "trace.jsonl")
    d = tmp_path / "ext"
    _write_ext(d, "good", """
        def register(api):
            api.log("hello")
    """)
    _write_ext(d, "bad", "import not_a_real_module_xyz\n")
    load_extensions(tmp_path, dirs=[d], trace=trace)
    rows = trace.load()
    events = {r["event"] for r in rows}
    assert "extension_loaded" in events and "extension_error" in events
    assert any(r["event"] == "extension_log" and r.get("msg") == "hello"
               for r in rows)


def test_registry_filter_domain_merge_and_default_unchanged():
    """域合并（有效白名单）+ 旧单参调用零变化（不回归）。"""
    from wuxing.extensions import ExtensionTool
    from wuxing.tools.base import ToolRegistry
    reg = ToolRegistry([])
    tool = ExtensionTool(name="ext_g", description="d", parameters={},
                         execute=lambda **kw: "x", domains=("execute",))
    assert reg.register_extension(tool, tool.domains) is True
    assert reg.register_extension(tool, tool.domains) is False  # 冲突拒绝
    assert [t.name() for t in reg.filter((), domain_id="execute")] == ["ext_g"]
    assert reg.filter((), domain_id="plan") == []
    assert reg.filter(()) == []  # 无域上下文：与旧行为一致


def test_validate_extension_dirs_list_items():
    """真实验证暴露：list 字段校验不得对整个列表套用 MCP 条目规则（E0-A 修复）。"""
    from wuxing.config_schema import validate_config
    assert validate_config({"extension_dirs": ["../exts"]}) == []
    assert validate_config({"extension_dirs": []}) == []
    errs = validate_config({"extension_dirs": [1]})
    assert errs and "extension_dirs[0]" in errs[0]


def test_validate_mcp_servers_items_still_enforced():
    """回归：MCP 条目校验不变（name/command|url）。"""
    from wuxing.config_schema import validate_config
    ok = validate_config({"mcp_servers": [{"name": "srv",
                                            "command": "npx"}]})
    assert ok == []
    errs = validate_config({"mcp_servers": [{"name": "srv"}]})
    assert errs and "command" in errs[0]


def test_engine_zero_behavior_without_extensions(tmp_path):
    """未安装扩展：不加载、无钩子、包装零行为（既有测试守护更广）。"""
    from wuxing.engine import Engine
    eng = Engine(workdir=tmp_path, auto_confirm=True)
    assert eng._extension_note == ""
    assert eng._ext_dispatcher.has_hooks() is False
    fn = lambda ev: None
    assert eng._wrap_events(fn) is fn


def test_engine_loads_extension_and_hook_receives_events(tmp_path):
    """钩子在真实任务链路留痕（trace extension_log）+ 工具注册进引擎工具面。"""
    from wuxing.config import EngineConfig
    from wuxing.engine import Engine
    d = tmp_path / "exts"
    _write_ext(d, "audit", """
        def register(api):
            api.log("loaded")
            api.on("TaskDone", lambda ev: api.log(f"TaskDone {ev.status}"))
            api.register_tool(name="ext_ping", description="ping",
                              parameters={}, execute=lambda **kw: "pong",
                              domains=("execute",), permission={"read": True})
    """)
    cfg = EngineConfig(extension_dirs=[str(d)])
    eng = Engine(cfg=cfg, workdir=tmp_path, auto_confirm=True)
    assert eng._extension_note == ""
    assert eng.tools.get("ext_ping") is not None
    res = eng.run_task("写一篇请假邮件")
    assert res.status == "done"
    rows = eng.trace.load()
    assert any(r["event"] == "extension_loaded" for r in rows)
    assert any(r["event"] == "extension_log" and r.get("msg") == "loaded"
               for r in rows)
    assert any(r["event"] == "extension_log"
               and str(r.get("msg", "")).startswith("TaskDone")
               for r in rows)


def test_engine_extension_disabled_switch(tmp_path):
    """显式关闭（D2）：不加载扩展（目录存在也不生效）。"""
    from wuxing.config import EngineConfig
    from wuxing.engine import Engine
    d = tmp_path / "exts"
    _write_ext(d, "audit", """
        def register(api):
            api.on("TaskDone", lambda ev: api.log("x"))
    """)
    cfg = EngineConfig(extension_enabled=False, extension_dirs=[str(d)])
    eng = Engine(cfg=cfg, workdir=tmp_path, auto_confirm=True)
    assert eng._ext_dispatcher.has_hooks() is False


def test_engine_broken_extension_visible_in_report(tmp_path):
    """broken 可见：报告注记（不阻断任务）——设计 §2.1/§4。"""
    from wuxing.config import EngineConfig
    from wuxing.engine import Engine
    d = tmp_path / "exts"
    _write_ext(d, "bad", "import not_a_real_module_xyz\n")
    cfg = EngineConfig(extension_dirs=[str(d)])
    eng = Engine(cfg=cfg, workdir=tmp_path, auto_confirm=True)
    assert eng._extension_note.startswith("[扩展] 1 个加载失败：")
    res = eng.run_task("写一篇请假邮件")
    assert "[扩展]" in res.report
