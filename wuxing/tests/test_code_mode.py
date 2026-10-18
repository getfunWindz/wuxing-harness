"""TDD · A4 Code Mode Phase 1（脚本执行通道）。

默认关；启用后脚本内受限 API（unit 白名单 ∩ code_mode_tools）经统一守卫链；
中间结果留在脚本进程，仅 stdout 回传。容器档不支持（loud）。
"""
import json
import time

from wuxing.config import EngineConfig
from wuxing.tools.base import ToolRegistry
from wuxing.tools.bash_tool import BashTool
from wuxing.tools.builtin import BUILTIN_TOOLS
from wuxing.tools.code_mode import RunScriptTool
from wuxing.tools.fs_tools import ReadFileTool, WriteFileTool
from wuxing.tools.search_tools import GlobTool, GrepTool
from wuxing.workspace import Workspace

WL = {"read_file", "write_file", "write_artifact", "read_dependency",
      "grep", "glob", "bash"}


def _mk(tmp_path, cfg=None, whitelist=None):
    ws = Workspace(tmp_path)
    cfg = cfg or EngineConfig(code_mode_enabled=True)
    (tmp_path / "hello.txt").write_text("你好\nline2\n", encoding="utf-8")
    tools = ([ReadFileTool(ws), WriteFileTool(ws), GrepTool(ws), GlobTool(ws)]
             + BUILTIN_TOOLS(ws)
             + [BashTool(ws, sandbox_enabled=True, sandbox_mode="native")])
    reg = ToolRegistry(tools)
    t = RunScriptTool(ws, cfg)
    reg.register(t)
    t.set_context(registry=reg,
                  whitelist=set(whitelist if whitelist is not None else WL))
    return t, ws


def test_config_defaults_off_and_fieldspec():
    from wuxing.config_schema import FIELD_SPECS
    cfg = EngineConfig()
    assert cfg.code_mode_enabled is False
    names = {s.name for s in FIELD_SPECS}
    for key in ("code_mode_enabled", "code_mode_timeout_s",
                "code_mode_max_calls", "code_mode_output_max_chars",
                "code_mode_tools"):
        assert key in names, key


def test_engine_registers_only_when_enabled(tmp_path):
    from wuxing.engine import Engine
    on = Engine(cfg=EngineConfig(llm="mock", code_mode_enabled=True),
                workdir=tmp_path)
    assert on.tools.get("run_script") is not None
    off = Engine(cfg=EngineConfig(llm="mock"), workdir=tmp_path)
    assert off.tools.get("run_script") is None


def test_happy_path_intermediate_stays_in_script(tmp_path):
    t, _ws = _mk(tmp_path)
    script = (
        'data = read_file(path="hello.txt")\n'
        'write_file(path="out.txt", content="N=%d" % len(data))\n'
        'print("DONE", len(data))\n')
    res = t.execute(script=script)
    assert res.status == "ok", res.error
    assert "DONE" in res.content
    assert "你好" not in res.content          # 中间结果未回传上下文
    assert (tmp_path / "out.txt").read_text(encoding="utf-8") == "N=9"


def test_whitelist_denied_in_script(tmp_path):
    t, _ws = _mk(tmp_path, whitelist={"read_file"})
    res = t.execute(script='grep(pattern="x", path=".")\nprint("NG")')
    assert res.status == "error"
    assert "not allowed" in (res.error or "") or "not allowed" in res.content


def test_max_calls_enforced(tmp_path):
    t, _ws = _mk(tmp_path, cfg=EngineConfig(code_mode_enabled=True,
                                           code_mode_max_calls=2))
    script = ("\n".join('read_file(path="hello.txt")' for _ in range(5))
              + '\nprint("END")\n')
    res = t.execute(script=script)
    assert res.status == "error"
    assert "上限" in (res.error or "")


def test_timeout_kills_tree(tmp_path):
    t, _ws = _mk(tmp_path, cfg=EngineConfig(code_mode_enabled=True,
                                           code_mode_timeout_s=2.0))
    t0 = time.time()
    res = t.execute(script="import time\ntime.sleep(30)\n")
    elapsed = time.time() - t0
    assert res.status == "error" and "timeout" in (res.error or "")
    assert elapsed < 15


def test_output_capped_and_dumped(tmp_path):
    t, _ws = _mk(tmp_path, cfg=EngineConfig(code_mode_enabled=True,
                                           code_mode_output_max_chars=200))
    res = t.execute(script='print("A" * 5000)\n')
    assert res.status == "ok"
    assert "已截断" in res.content
    dumps = list((tmp_path / ".wuxing" / "code").glob("*.out"))
    assert dumps and len(dumps[0].read_text(encoding="utf-8")) > 5000


def test_bash_guard_blocks_dangerous(tmp_path):
    from wuxing.permissions import apply_tool_policy
    t, _ws = _mk(tmp_path)
    apply_tool_policy(t._ctx["registry"], "workspace-write")
    res = t.execute(script='bash(command="rm -rf /")\nprint("NG")\n')
    assert res.status == "error"
    assert "根" in (res.error or "") or "blocked" in (res.error or "")


def test_path_escape_denied(tmp_path):
    t, _ws = _mk(tmp_path)
    res = t.execute(script='read_file(path="../../outside.txt")\nprint("NG")')
    assert res.status == "error"


def test_trace_events(tmp_path):
    from wuxing.trace import TraceLogger
    trace = TraceLogger(tmp_path / "trace.jsonl")
    t, _ws = _mk(tmp_path)
    t.set_context(registry=t._ctx["registry"], whitelist=WL, trace=trace,
                  unit_id="U-1", domain_id="execute")
    res = t.execute(script='read_file(path="hello.txt")\nprint("OK")\n')
    assert res.status == "ok"
    rows = [json.loads(x) for x in
            (tmp_path / "trace.jsonl").read_text(encoding="utf-8").splitlines()
            if x.strip()]
    assert any(r.get("event") == "code_mode_run" for r in rows)
    assert any(r.get("event") == "tool_call" and r.get("via") == "code_mode"
               for r in rows)


def test_runner_injects_context(tmp_path):
    """runner 链路：run_script 经 _execute_toolcall 注入上下文并真实执行。"""
    from wuxing.llm.tool_results import ToolCallResult
    from wuxing.registry import DomainRegistry
    from wuxing.runner import Runner

    class _Llm:
        def __init__(self):
            self.calls = 0
            self.seen = []

        def name(self):
            return "script-llm"

        def chat(self, messages, tools=None):
            self.calls += 1
            self.seen.append([dict(m) for m in messages])
            if self.calls == 1:
                return ToolCallResult(text="", tool_calls=[{
                    "name": "run_script",
                    "arguments": {"script": 'print("PONG")'}}])
            return ToolCallResult(text="完成", tool_calls=[{
                "name": "write_artifact",
                "arguments": {"path": "x.md", "kind": "result",
                              "content": "v"}}])

    ws = Workspace(tmp_path)
    cfg = EngineConfig(max_loop_rounds=2, max_unit_budget=2,
                       code_mode_enabled=True)
    llm = _Llm()
    t = RunScriptTool(ws, cfg)
    tools = ToolRegistry([ReadFileTool(ws), WriteFileTool(ws)]
                         + BUILTIN_TOOLS(ws) + [t])
    r = Runner(cfg, DomainRegistry(cfg), ws, llm, tools)
    r.run_unit("U-1", "execute", {"goal": "g", "task": "t"})
    assert any("PONG" in str(m.get("content", ""))
               for msgs in llm.seen for m in msgs)


def test_inner_calls_reported_to_callback(tmp_path):
    """O3/C4：脚本内 write_file 上报（写物证对齐入口）。"""
    collected = []
    t, _ws = _mk(tmp_path)
    t.set_context(registry=t._ctx["registry"], whitelist=WL, trace=None,
                  unit_id="U-1", domain_id="execute",
                  on_inner_call=lambda name, args, status, content:
                      collected.append((name, args.get("path"), status)))
    res = t.execute(script='write_file(path="inner.txt", content="x")\n'
                           'print("OK")')
    assert res.status == "ok", res.error
    assert ("write_file", "inner.txt", "ok") in collected


def test_runner_script_write_counts_as_evidence(tmp_path):
    """O3/C4：脚本内写操作经回调计入 runner 物证（write_ok/deliverables）。"""
    from wuxing.llm.tool_results import ToolCallResult
    from wuxing.registry import DomainRegistry
    from wuxing.runner import Runner

    class _Llm:
        def __init__(self):
            self.calls = 0

        def name(self):
            return "script-write-llm"

        def chat(self, messages, tools=None):
            self.calls += 1
            if self.calls == 1:
                return ToolCallResult(text="", tool_calls=[{
                    "name": "run_script",
                    "arguments": {"script":
                                  'write_file(path="scripted.md", content="hi")\n'
                                  'print("WROTE")'}}])
            return "执行完成：scripted.md 已产出"

    ws = Workspace(tmp_path)
    cfg = EngineConfig(max_loop_rounds=3, max_unit_budget=4,
                       code_mode_enabled=True)
    tool = RunScriptTool(ws, cfg)
    tools = ToolRegistry([ReadFileTool(ws), WriteFileTool(ws)]
                         + BUILTIN_TOOLS(ws) + [tool])
    r = Runner(cfg, DomainRegistry(cfg), ws, _Llm(), tools)
    res = r.run_unit("U-1", "execute", {"goal": "写一个文件"})
    assert res.status == "ok", res.error
    assert r._write_ok is True
    assert "scripted.md" in r._deliverables
