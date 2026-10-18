"""E2：扩展二期（提示词段 / 干预钩子 / 命令 / preset）——分批追加。"""
import json
import pathlib

import pytest


def _write_ext(root, name, body):
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{name}.py").write_text(body, encoding="utf-8")


# ---------- E2-1 提示词段 ----------

def test_add_prompt_segment_validation():
    from wuxing.extensions import ExtensionAPI
    api = ExtensionAPI(workdir=".", source="s", log_fn=lambda *a: None)
    with pytest.raises(ValueError):
        api.add_prompt_segment("  ")
    with pytest.raises(ValueError):
        api.add_prompt_segment("x" * 2001)
    api.add_prompt_segment("规则A", domains=["execute"])
    assert api.pending_segments[0]["source"] == "s"
    assert api.pending_segments[0]["domains"] == ("execute",)


def test_load_commits_prompt_segments(tmp_path):
    from wuxing.extensions import load_extensions
    d = tmp_path / "ext"
    _write_ext(d, "seg",
               "def register(api):\n"
               "    api.add_prompt_segment('必须写测试')\n")
    res = load_extensions(tmp_path, enabled=True, dirs=[d])
    assert res.prompt_segments[0]["text"] == "必须写测试"


def test_runner_injects_segment_and_trace(tmp_path):
    from wuxing.config import EngineConfig
    from wuxing.engine import Engine
    d = tmp_path / ".wuxing" / "extensions"
    _write_ext(d, "seg",
               "def register(api):\n"
               "    api.add_prompt_segment('扩展规则：只读优先', domains=('execute',))\n")
    eng = Engine(cfg=EngineConfig(use_real_shape=False), workdir=tmp_path)
    res = eng.run_task("写一篇请假邮件")
    assert res.status == "done"
    trace = (tmp_path / ".wuxing" / "trace.jsonl").read_text(encoding="utf-8")
    assert "extension_prompt" in trace


def test_pure_mode_no_segment(tmp_path):
    from wuxing.config import EngineConfig
    from wuxing.engine import Engine
    from wuxing.session_modes import save as save_mode
    d = tmp_path / ".wuxing" / "extensions"
    _write_ext(d, "seg",
               "def register(api):\n"
               "    api.add_prompt_segment('不应注入')\n")
    save_mode(tmp_path, "conversation-w.jsonl", "minimal", "pure")
    eng = Engine(cfg=EngineConfig(use_real_shape=False), workdir=tmp_path)
    from wuxing.conversation import ConversationState
    conv = ConversationState(tmp_path / ".wuxing" / "conversation-w.jsonl")
    eng.run_task("写一篇请假邮件", conversation=conv)
    trace = (tmp_path / ".wuxing" / "trace.jsonl").read_text(encoding="utf-8")
    assert "extension_prompt" not in trace


def test_no_segments_zero_behavior(tmp_path):
    from wuxing.config import EngineConfig
    from wuxing.engine import Engine
    eng = Engine(cfg=EngineConfig(use_real_shape=False), workdir=tmp_path)
    eng.run_task("写一篇请假邮件")
    trace = (tmp_path / ".wuxing" / "trace.jsonl").read_text(encoding="utf-8")
    assert "extension_prompt" not in trace


# ---------- E2-2 干预钩子 ----------

def test_dispatch_first_first_value_wins_and_isolated():
    from wuxing.extensions import EventDispatcher, ToolCallRequested
    d = EventDispatcher()
    order = []

    def h1(event):
        order.append("h1")
        raise RuntimeError("boom")

    def h2(event):
        order.append("h2")
        return {"args": {"x": 2}}

    def h3(event):
        order.append("h3")
        return {"deny": "no"}

    d.add("ToolCallRequested", h1, source="e1")
    d.add("ToolCallRequested", h2, source="e2")
    d.add("ToolCallRequested", h3, source="e3")
    res = d.dispatch_first(ToolCallRequested(name="bash", args={"x": 1}))
    assert res == {"args": {"x": 2}}
    assert order == ["h1", "h2"]          # 首值胜出；异常隔离继续


def test_tool_interceptor_modifies_args(tmp_path):
    from wuxing.config import EngineConfig
    from wuxing.engine import Engine
    d = tmp_path / ".wuxing" / "extensions"
    _write_ext(d, "rewrite", '''
def register(api):
    def hook(event):
        if event.name == "echo_tool":
            return {"args": {"msg": "改后"}}
    api.on("ToolCallRequested", hook)
    api.register_tool(
        name="echo_tool", description="echo",
        parameters={"type": "object", "properties": {"msg": {"type": "string"}}},
        execute=lambda msg="": {"got": msg}, domains=("execute",),
        permission={"read": True})
''')
    eng = Engine(cfg=EngineConfig(use_real_shape=False), workdir=tmp_path)
    res = eng.tools.execute("echo_tool", msg="原")
    assert res.status == "ok"
    assert "改后" in json.dumps(res.content, ensure_ascii=False)


def test_tool_interceptor_deny(tmp_path):
    from wuxing.config import EngineConfig
    from wuxing.engine import Engine
    d = tmp_path / ".wuxing" / "extensions"
    _write_ext(d, "deny", '''
def register(api):
    def hook(event):
        if event.name == "echo_tool":
            return {"deny": "策略禁止"}
    api.on("ToolCallRequested", hook)
    api.register_tool(
        name="echo_tool", description="echo",
        parameters={"type": "object", "properties": {"msg": {"type": "string"}}},
        execute=lambda msg="": {"got": msg}, domains=("execute",),
        permission={"read": True})
''')
    eng = Engine(cfg=EngineConfig(use_real_shape=False), workdir=tmp_path)
    res = eng.tools.execute("echo_tool", msg="x")
    assert res.status == "error"
    assert "扩展拦截" in res.error
    trace = (tmp_path / ".wuxing" / "trace.jsonl").read_text(encoding="utf-8")
    assert "extension_tool_denied" in trace


def test_tool_interceptor_zero_behavior_without_extensions(tmp_path):
    from wuxing.config import EngineConfig
    from wuxing.engine import Engine
    eng = Engine(cfg=EngineConfig(use_real_shape=False), workdir=tmp_path)
    assert eng._ext_result.prompt_segments == []
    assert eng._ext_dispatcher.has_hooks() is False
    res = eng.tools.execute("read_file", path="nope.txt")
    assert res.status in ("ok", "error")   # 正常路径未被干预


# ---------- E3-2 P0：决策语义 v2（allow/deny/ask + updated_input + 合并） ----------

def test_dispatch_merge_deny_beats_allow_and_ask():
    """合并语义：deny > ask > allow（后序 allow 不得放宽前序 deny/ask）。"""
    from wuxing.extensions import EventDispatcher, ToolCallRequested
    ev = ToolCallRequested(name="bash", args={})
    d = EventDispatcher()
    d.add("ToolCallRequested", lambda e: {"decision": "allow"}, source="a1")
    d.add("ToolCallRequested", lambda e: {"decision": "ask", "reason": "看下"},
          source="a2")
    d.add("ToolCallRequested", lambda e: {"decision": "deny", "reason": "禁"},
          source="a3")
    merged = d.dispatch_merge(ev)
    assert merged["decision"] == "deny" and merged["reason"] == "禁"


def test_dispatch_merge_ask_beats_allow():
    """合并语义：ask 取代 allow（无 deny 时 ask 为最严）。"""
    from wuxing.extensions import EventDispatcher, ToolCallRequested
    d = EventDispatcher()
    d.add("ToolCallRequested", lambda e: {"decision": "allow"}, source="a")
    d.add("ToolCallRequested", lambda e: {"decision": "ask", "reason": "q"},
          source="b")
    merged = d.dispatch_merge(ToolCallRequested(name="t", args={}))
    assert merged["decision"] == "ask"


def test_dispatch_merge_first_updated_input_wins():
    """合并语义：updated_input 取首个提供者（注册顺序）。"""
    from wuxing.extensions import EventDispatcher, ToolCallRequested
    d = EventDispatcher()
    d.add("ToolCallRequested", lambda e: {"updated_input": {"x": 2}}, source="a")
    d.add("ToolCallRequested",
          lambda e: {"decision": "allow", "updated_input": {"x": 3}}, source="b")
    merged = d.dispatch_merge(ToolCallRequested(name="t", args={"x": 1}))
    assert merged["updated_input"] == {"x": 2}
    assert merged["decision"] == "allow"


def test_dispatch_merge_back_compat_and_none():
    """兼容旧契约（deny/args）与空决策（全 None → None）。"""
    from wuxing.extensions import EventDispatcher, ToolCallRequested
    d = EventDispatcher()
    d.add("ToolCallRequested", lambda e: None, source="a")
    assert d.dispatch_merge(ToolCallRequested(name="t", args={})) is None
    d2 = EventDispatcher()
    d2.add("ToolCallRequested", lambda e: {"args": {"x": 9}}, source="a")
    merged = d2.dispatch_merge(ToolCallRequested(name="t", args={"x": 1}))
    assert merged["decision"] == "allow" and merged["updated_input"] == {"x": 9}
    d3 = EventDispatcher()
    d3.add("ToolCallRequested", lambda e: {"deny": "旧契约"}, source="a")
    merged3 = d3.dispatch_merge(ToolCallRequested(name="t", args={}))
    assert merged3["decision"] == "deny" and merged3["reason"] == "旧契约"


def test_allow_does_not_bypass_guard():
    """E3-2 红线：钩子 allow 不得绕过守卫（interceptor → guard 顺序）。"""
    from wuxing.protocols import ToolResult
    from wuxing.tools.base import Tool, ToolRegistry

    class T(Tool):
        def name(self): return "t"
        def description(self): return "t"
        def input_schema(self):
            return {"type": "object", "properties": {}, "required": []}
        def permission(self): return {"read": True}
        def execute(self, **kw):
            return ToolResult(status="ok", content="ran", tool_name="t")

    reg = ToolRegistry([T()])
    reg.set_ext_interceptor(lambda n, k: {"decision": "allow"})
    reg.set_guard(lambda n, k: "禁跑")
    res = reg.execute("t")
    assert res.status == "blocked" and "禁跑" in res.error


def test_updated_input_still_validated_by_guard():
    """E3-2 红线：updated_input 改参后仍过守卫（不得用改参绕过）。"""
    from wuxing.protocols import ToolResult
    from wuxing.tools.base import Tool, ToolRegistry

    class T(Tool):
        def name(self): return "t"
        def description(self): return "t"
        def input_schema(self):
            return {"type": "object", "properties": {"cmd": {"type": "string"}},
                    "required": []}
        def permission(self): return {"read": True}
        def execute(self, **kw):
            return ToolResult(status="ok", content="ran", tool_name="t")

    reg = ToolRegistry([T()])
    reg.set_ext_interceptor(
        lambda n, k: {"decision": "allow", "updated_input": {"cmd": "rm"}})
    reg.set_guard(lambda n, k: ("禁危险" if k.get("cmd") == "rm" else True))
    res = reg.execute("t", cmd="ls")
    assert res.status == "blocked" and "禁危险" in res.error


def test_tool_interceptor_ask_fail_closed(tmp_path):
    """E3-2：ask = fail-closed 延后（不执行 + 提示确认 + trace extension_tool_ask）。"""
    from wuxing.config import EngineConfig
    from wuxing.engine import Engine
    d = tmp_path / ".wuxing" / "extensions"
    _write_ext(d, "ask", '''
import pathlib

def register(api):
    def hook(event):
        if event.name == "marker_tool":
            return {"decision": "ask", "reason": "需用户确认"}
    def run(msg=""):
        p = pathlib.Path(api.workdir) / ".wuxing"
        p.mkdir(parents=True, exist_ok=True)
        (p / "ask-ran.flag").write_text("ran", encoding="utf-8")
        return {"got": msg}
    api.on("ToolCallRequested", hook)
    api.register_tool(
        name="marker_tool", description="marker",
        parameters={"type": "object", "properties": {"msg": {"type": "string"}}},
        execute=run, domains=("execute",), permission={"read": True})
''')
    eng = Engine(cfg=EngineConfig(use_real_shape=False), workdir=tmp_path)
    res = eng.tools.execute("marker_tool", msg="x")
    assert res.status == "error"
    assert "扩展询问" in res.error and "需用户确认" in res.error
    assert not (tmp_path / ".wuxing" / "ask-ran.flag").exists(), \
        "ask 必须 fail-closed（工具不得执行）"
    trace = (tmp_path / ".wuxing" / "trace.jsonl").read_text(encoding="utf-8")
    assert "extension_tool_ask" in trace


def test_tool_interceptor_updated_input_v2(tmp_path):
    """E3-2：updated_input 契约（等价改参；trace 记键名）。"""
    from wuxing.config import EngineConfig
    from wuxing.engine import Engine
    d = tmp_path / ".wuxing" / "extensions"
    _write_ext(d, "upd", '''
def register(api):
    def hook(event):
        if event.name == "echo_tool":
            return {"decision": "allow", "updated_input": {"msg": "改后"}}
    api.on("ToolCallRequested", hook)
    api.register_tool(
        name="echo_tool", description="echo",
        parameters={"type": "object", "properties": {"msg": {"type": "string"}}},
        execute=lambda msg="": {"got": msg}, domains=("execute",),
        permission={"read": True})
''')
    eng = Engine(cfg=EngineConfig(use_real_shape=False), workdir=tmp_path)
    res = eng.tools.execute("echo_tool", msg="原")
    assert res.status == "ok"
    assert "改后" in json.dumps(res.content, ensure_ascii=False)
    trace = (tmp_path / ".wuxing" / "trace.jsonl").read_text(encoding="utf-8")
    assert "extension_tool_input_updated" in trace


# ---------- E2-3 命令扩展 ----------

def test_register_command_validation():
    from wuxing.extensions import ExtensionAPI
    api = ExtensionAPI(workdir=".", source="s", log_fn=lambda *a: None)
    with pytest.raises(ValueError):
        api.register_command("Bad Name", lambda args: "x")
    with pytest.raises(TypeError):
        api.register_command("ok-name", "not-callable")
    api.register_command("ok-name", lambda args: "x", description="d")
    assert api.pending_commands[0]["name"] == "ok-name"


def _engine_with_commands(tmp_path):
    from wuxing.config import EngineConfig
    from wuxing.engine import Engine
    d = tmp_path / ".wuxing" / "extensions"
    _write_ext(d, "cmds", '''
def register(api):
    def hello(args):
        return "你好 " + str(args.get("who") or "世界")
    def boom(args):
        raise RuntimeError("炸了")
    api.register_command("hello", hello, description="打招呼")
    api.register_command("boom", boom)
''')
    return Engine(cfg=EngineConfig(use_real_shape=False), workdir=tmp_path)


def test_engine_list_and_run_command(tmp_path):
    eng = _engine_with_commands(tmp_path)
    cmds = eng.list_commands()
    names = {c["name"] for c in cmds}
    assert {"hello", "boom"} <= names
    assert "handler" not in cmds[0]
    res = eng.run_command("hello", {"who": "扩展"})
    assert res["status"] == "ok" and "扩展" in res["text"]
    bad = eng.run_command("boom")
    assert bad["status"] == "error" and "炸了" in bad["error"]
    with pytest.raises(KeyError):
        eng.run_command("no-such")


def test_command_name_conflict_visible(tmp_path):
    from wuxing.extensions import load_extensions
    d = tmp_path / "ext"
    _write_ext(d, "c1", "def register(api):\n"
                        "    api.register_command('same', lambda a: '1')\n")
    _write_ext(d, "c2", "def register(api):\n"
                        "    api.register_command('same', lambda a: '2')\n")
    res = load_extensions(tmp_path, enabled=True, dirs=[d])
    assert any(c["name"] == "same" for c in res.commands)
    assert any("命令名冲突" in p for p in res.problems)


def test_cli_ext_list_and_run(tmp_path):
    import subprocess
    import sys
    eng_dir = tmp_path / "ws"
    (eng_dir / ".wuxing" / "extensions").mkdir(parents=True)
    (eng_dir / ".wuxing" / "extensions" / "cmds.py").write_text(
        "def register(api):\n"
        "    api.register_command('hello', lambda args: '来自 CLI')\n",
        encoding="utf-8")
    import os
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    base = [sys.executable, "-m", "wuxing.cli", "ext"]
    r1 = subprocess.run(base + ["list", "--workdir", str(eng_dir)],
                        capture_output=True, text=True, check=False,
                        encoding="utf-8", errors="replace", env=env,
                        cwd=str(pathlib.Path(__file__).resolve().parents[2]))
    assert r1.returncode == 0 and "hello" in r1.stdout
    r2 = subprocess.run(base + ["run", "hello", "--workdir", str(eng_dir)],
                        capture_output=True, text=True, check=False,
                        encoding="utf-8", errors="replace", env=env,
                        cwd=str(pathlib.Path(__file__).resolve().parents[2]))
    assert r2.returncode == 0 and "来自 CLI" in r2.stdout


# ---------- E2-UI 命令参数声明 ----------

def test_register_command_args_validation():
    from wuxing.extensions import ExtensionAPI
    api = ExtensionAPI(workdir=".", source="s", log_fn=lambda *a: None)
    api.register_command("sum", lambda a: "1", args=[
        {"name": "a", "label": "加数 A", "type": "int", "required": True},
        {"name": "b", "type": "float", "default": 1},
        {"name": "verbose", "type": "bool", "default": False},
        {"name": "note", "type": "str"},
    ])
    spec = api.pending_commands[0]["args"]
    assert spec[0] == {"name": "a", "label": "加数 A", "type": "int",
                       "required": True, "default": None}
    assert spec[1]["label"] == "b"            # label 缺省 = name
    assert spec[3]["required"] is False
    # 无声明 → 空列表（零行为）
    api.register_command("noargs", lambda a: "1")
    assert api.pending_commands[1]["args"] == []

    for bad in (
        [{"name": "Bad"}],                              # 非法名
        [{"name": "a", "type": "list"}],                # 非法类型
        [{"name": "a"}, {"name": "a"}],                # 重复名
        [{"name": "a", "type": "int", "default": "x"}],  # 默认值类型不符
    ):
        with pytest.raises(ValueError):
            api.register_command("sum2", lambda a: "1", args=bad)
    with pytest.raises(TypeError):              # 非对象声明（类型错误）
        api.register_command("sum2", lambda a: "1", args=["nope"])


def test_coerce_command_args():
    from wuxing.extensions import coerce_command_args
    schema = [
        {"name": "a", "label": "A", "type": "int", "required": True, "default": None},
        {"name": "b", "label": "B", "type": "float", "required": False, "default": 1},
        {"name": "c", "label": "C", "type": "bool", "required": False, "default": None},
        {"name": "d", "label": "D", "type": "str", "required": False, "default": "x"},
    ]
    values, err = coerce_command_args(schema, {"a": "41", "c": "true", "extra": 7})
    assert err == ""
    assert values["a"] == 41 and isinstance(values["a"], int)
    assert values["b"] == 1.0 and isinstance(values["b"], float)  # 默认值同路径转换
    assert values["c"] is True
    assert values["d"] == "x"
    assert values["extra"] == 7               # 未声明键透传（CLI 兼容）
    # 必填缺失 → 错误消息含显示名
    _, err2 = coerce_command_args(schema, {})
    assert "A" in err2
    # 数值非法
    _, err3 = coerce_command_args(schema, {"a": "abc"})
    assert "A" in err3
    # 空 schema：只透传
    vals, err4 = coerce_command_args([], {"k": 1})
    assert err4 == "" and vals == {"k": 1}


def test_engine_command_args(tmp_path):
    from wuxing.config import EngineConfig
    from wuxing.engine import Engine
    d = tmp_path / ".wuxing" / "extensions"
    _write_ext(d, "sum", '''
def register(api):
    def add(args):
        return "sum=" + str(int(args["a"]) + int(args["b"]))
    api.register_command("add", add, description="求和", args=[
        {"name": "a", "type": "int", "required": True},
        {"name": "b", "type": "int", "default": 1},
    ])
''')
    eng = Engine(cfg=EngineConfig(use_real_shape=False), workdir=tmp_path)
    cmd = next(c for c in eng.list_commands() if c["name"] == "add")
    assert cmd["args"][0]["name"] == "a"
    assert cmd["args"][0]["required"] is True
    assert cmd["args"][1]["default"] == 1
    res = eng.run_command("add", {"a": "41"})
    assert res["status"] == "ok" and res["text"] == "sum=42"
    bad = eng.run_command("add", {})
    assert bad["status"] == "error" and "a" in bad["error"]
    # 无 args 声明的旧命令不受影响（零行为）
    eng2 = _engine_with_commands(tmp_path / "second")
    hello = next(c for c in eng2.list_commands() if c["name"] == "hello")
    assert hello["args"] == []
