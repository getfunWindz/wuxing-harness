"""TDD · M1-4：工具级并行——read 突发并发化 + 副作用点串行化（CPU 速度主轴）。

设计（机制裁决）：
  - 无副作用工具（read_file/read_dependency/load_skill）→ 组内并发执行（Barrier 证明）
  - 有副作用工具（write/bash/delegate）→ 按模型发出顺序串行（顺序语义保持）
  - 日志回填顺序 = 模型调用顺序（并发完成但回填不乱序——消息语义稳定）
"""
import pathlib
import tempfile
import threading
import time

from wuxing.config import EngineConfig
from wuxing.registry import DomainRegistry
from wuxing.runner import Runner
from wuxing.tools.base import Tool, ToolRegistry
from wuxing.workspace import Workspace


class _T(Tool):
    def __init__(self, name, desc, marker=None, sleep=0.0, side_effect=False):
        self._n, self._d, self._marker = name, desc, marker
        self._sleep, self._side = sleep, side_effect
        self.scope = {"permission": ("read" if not side_effect else "write")}

    def name(self):
        return self._n

    def description(self):
        return self._d

    def input_schema(self):
        return {"type": "object", "properties": {}, "required": []}

    def permission(self):
        return {"read": not self._side, "write": self._side,
                "execute": False, "network": False, "destructive": False}

    def execute(self, **kw):
        from wuxing.protocols import ToolResult
        if self._sleep:
            time.sleep(self._sleep)
        if self._marker is not None:
            self._marker.append(self._n)
            self._marker.append("|")  # 分隔
        return ToolResult(status="ok", content=f"ok-{self._n}", tool_name=self._n)


def test_read_batch_runs_concurrently():
    """无副作用工具组并发（Barrier 证明真正同时执行——非串行）。"""
    barrier = threading.Barrier(3, timeout=10)
    reached = {"n": 0, "lock": threading.Lock()}

    class B(_T):
        def execute(self, **kw):
            barrier.wait()
            with reached["lock"]:
                reached["n"] += 1
            return super().execute(**kw)

    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    reg = ToolRegistry([B("read_file", "读 a"), B("read_dependency", "读 b"), B("load_skill", "读 c")])
    cfg = EngineConfig(max_loop_rounds=2, max_unit_budget=2)
    r = Runner(cfg, DomainRegistry(cfg), ws, None, reg)
    # 直接测批量执行路径（_execute_tool_calls_batch）
    calls = [{"name": "read_file", "arguments": {}},
             {"name": "read_dependency", "arguments": {}},
             {"name": "load_skill", "arguments": {}}]
    logs = []
    r._execute_tool_calls_batch(calls, reg.list(), logs, unit_id="U")
    assert reached["n"] == 3, "三个无副作用工具必须并发执行（串行则 Barrier 超时）"
    assert any("read_file" in l for l in logs), "每个工具结果都需回填"
    assert len(logs) == 3


def test_side_effect_tools_stay_sequential():
    """有副作用工具（write/bash/delegate）按顺序串行——顺序语义保持。"""
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    marker = []  # 顺序记录（断言保序）
    reg = ToolRegistry([
        _T("write_artifact", "写 1", marker=marker, side_effect=True, sleep=0.05),
        _T("bash", "执行", marker=marker, side_effect=True, sleep=0.05),
        _T("write_file", "写 2", marker=marker, side_effect=True, sleep=0.05),
    ])
    cfg = EngineConfig(max_loop_rounds=2, max_unit_budget=2)
    r = Runner(cfg, DomainRegistry(cfg), ws, None, reg)
    calls = [{"name": "write_artifact", "arguments": {}},
             {"name": "bash", "arguments": {}},
             {"name": "write_file", "arguments": {}}]
    logs = []
    r._execute_tool_calls_batch(calls, reg.list(), logs, unit_id="U")
    seq = [x for x in marker if x != "|"]
    assert seq == ["write_artifact", "bash", "write_file"], \
        f"副作用工具必须保持顺序：{seq}"


def test_logs_backfilled_in_call_order():
    """日志回填顺序 = 模型调用顺序（并发完成但消息语义不乱序）。"""
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    reg = ToolRegistry([
        _T("read_file", "读 a", marker=None, sleep=0.10),
        _T("read_dependency", "读 b", marker=None, sleep=0.0),
        _T("load_skill", "读 c", marker=None, sleep=0.05),
    ])
    cfg = EngineConfig(max_loop_rounds=2, max_unit_budget=2)
    r = Runner(cfg, DomainRegistry(cfg), ws, None, reg)
    calls = [{"name": "read_file", "arguments": {}},
             {"name": "read_dependency", "arguments": {}},
             {"name": "load_skill", "arguments": {}}]
    logs = []
    r._execute_tool_calls_batch(calls, reg.list(), logs, unit_id="U")
    names = []
    for l in logs:
        if l.startswith("[tool]"):
            names.append(l.split()[1].split(":")[0])
    assert names == ["read_file", "read_dependency", "load_skill"], \
        f"回填顺序须与调用序一致：{names}"


def test_mcp_readonly_tool_parallel_safe():
    """E2：MCP 只读工具（permission read=True 其余 False）→ 归入无副作用组并发执行。
    机制判定（机械——非模型自觉）：permission 声明 read 仅读 → 组内并发安全。"""
    from wuxing.config import EngineConfig
    from wuxing.protocols import ToolResult
    from wuxing.registry import DomainRegistry
    from wuxing.tools.base import Tool, ToolRegistry
    from wuxing.tools.builtin import BUILTIN_TOOLS
    from wuxing.workspace import Workspace

    class FakeMcp(Tool):
        def __init__(self, name):
            self._n = name
            self.is_mcp = True

        def name(self):
            return self._n

        def description(self):
            return "fake mcp read-only"

        def input_schema(self):
            return {"type": "object", "properties": {"q": {"type": "string"}}}

        def permission(self):
            return {"read": True, "write": False, "execute": False,
                    "network": False, "destructive": False}

        def execute(self, q="", **kw):
            return ToolResult(status="ok", content=f"{self._n}:{q}",
                              tool_name=self.name())

    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    cfg = EngineConfig(max_loop_rounds=3, max_unit_budget=3, max_parallel_units=1)
    reg = DomainRegistry(cfg)
    reg._domains["execute"] = __import__(
        "wuxing.domains.defaults", fromlist=["DEFAULT_DOMAINS"]
    ).DEFAULT_DOMAINS["execute"]

    class ParallelProbe:
        def __init__(self):
            self.usage_history = []
            self.call_count = 0

        def name(self):
            return "pp"

        def spec(self):
            return "pp"

        def supports_native_tools(self):
            return False

        def chat(self, messages, tools=None):
            from wuxing.llm.tool_results import ToolCallResult
            self.usage_history.append({"input": 0, "output": 0,
                                       "cache_read": 0, "cache_write": 0})
            self.call_count += 1
            # 两个 MCP 只读工具 + 写物证——同批并行
            return ToolCallResult(text="执行完成", tool_calls=[
                {"name": "srv_query", "arguments": {"q": "a"}},
                {"name": "srv_meta", "arguments": {"q": "b"}},
                {"name": "write_artifact", "arguments": {
                    "path": "out.md", "kind": "result", "content": "x"}},
            ])

    registry = ToolRegistry([FakeMcp("srv_query"), FakeMcp("srv_meta")]
                            + BUILTIN_TOOLS(ws))
    # 域白名单需含 mcp:*（E2 场景：MCP 工具白名单前缀放行）
    from wuxing.tools.base import whitelist_accepts
    assert whitelist_accepts("srv_query", ("write_artifact", "mcp:*"), is_mcp=True)

    # 直接验证「只读 MCP → 无副作用组」判定（单元）
    from wuxing.runner import _is_side_effect_free as _sef
    assert _sef("srv_query", registry), "只读 MCP 工具必须归属无副作用组"
    assert not _sef("write_artifact", registry), "写工具不得归属无副作用组"


def test_readonly_permission_tools_parallel_x5():
    """E3-1/X5：权限声明只读（read=True 其余 False）的内置工具 → 并行组。

    grep/glob/session_search 此前不在静态表 → 串行；声明式推导（X5）后并发。
    """
    barrier = threading.Barrier(3, timeout=10)
    reached = {"n": 0, "lock": threading.Lock()}

    class B(_T):
        def execute(self, **kw):
            barrier.wait()
            with reached["lock"]:
                reached["n"] += 1
            return super().execute(**kw)

    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    reg = ToolRegistry([B("grep", "搜索"), B("glob", "文件匹配"),
                        B("session_search", "检索")])
    cfg = EngineConfig(max_loop_rounds=2, max_unit_budget=2)
    r = Runner(cfg, DomainRegistry(cfg), ws, None, reg)
    calls = [{"name": "grep", "arguments": {}},
             {"name": "glob", "arguments": {}},
             {"name": "session_search", "arguments": {}}]
    logs = []
    r._execute_tool_calls_batch(calls, reg.list(), logs, unit_id="U")
    assert reached["n"] == 3, "权限只读工具必须并发（串行则 Barrier 超时）"
    assert len(logs) == 3


def test_is_side_effect_free_permission_derived():
    """E3-1/X5：判定 = 静态种子 + 权限声明推导（read=True 且其余全假）。"""
    from wuxing.runner import _is_side_effect_free

    class Net(_T):
        def permission(self):
            return {"read": True, "write": False, "execute": False,
                    "network": True, "destructive": False}

    reg = ToolRegistry([_T("grep", "读"),
                        _T("write_file", "写", side_effect=True),
                        Net("web_fetch", "网")])
    assert _is_side_effect_free("grep", reg) is True
    assert _is_side_effect_free("read_file", reg) is True   # 静态种子（未注册）
    assert _is_side_effect_free("write_file", reg) is False
    assert _is_side_effect_free("web_fetch", reg) is False  # 网络类不并行


def test_exclusive_call_acts_as_barrier():
    """E3-1/D2：独占调用（写/执行）构成批次屏障——执行序=模型调用序。

    顺序不变量：grep（读）→ write_file（写·屏障）→ glob（读）
    屏障前读批必须先完成；屏障后读批不得提前（隔离批次，不得跨越写重排）。
    """
    marker = []
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    reg = ToolRegistry([
        _T("grep", "读", marker=marker, sleep=0.05),
        _T("write_file", "写", marker=marker, side_effect=True, sleep=0.02),
        _T("glob", "读2", marker=marker, sleep=0.01),
    ])
    cfg = EngineConfig(max_loop_rounds=2, max_unit_budget=2)
    r = Runner(cfg, DomainRegistry(cfg), ws, None, reg)
    calls = [{"name": "grep", "arguments": {}},
             {"name": "write_file", "arguments": {}},
             {"name": "glob", "arguments": {}}]
    logs = []
    r._execute_tool_calls_batch(calls, reg.list(), logs, unit_id="U")
    seq = [x for x in marker if x != "|"]
    assert seq == ["grep", "write_file", "glob"], \
        f"独占屏障语义破坏（执行序须等于调用序）：{seq}"
    names = []
    for l in logs:
        if l.startswith("[tool]"):
            names.append(l.split()[1].split(":")[0])
    assert names == ["grep", "write_file", "glob"], \
        f"回填顺序须与调用序一致：{names}"


def test_reads_split_across_barrier_not_merged():
    """E3-1/D2：读批不得跨越屏障合并——写前读与写后读是两个独立批次。

    证明方式：写前读与写后读同名工具，若被错误合并为一批并发执行，
    屏障测试的 Barrier 口径会超时；此处用「写前读必须早于写完成」锚定。
    """
    order = []
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))

    class W(_T):
        def execute(self, **kw):
            order.append("write-start")
            time.sleep(0.05)
            order.append("write-end")
            return super().execute(**kw)

    reg = ToolRegistry([
        _T("grep", "读", marker=order, sleep=0.02),
        W("write_file", "写", side_effect=True),
        _T("glob", "读2", marker=order, sleep=0.0),
    ])
    cfg = EngineConfig(max_loop_rounds=2, max_unit_budget=2)
    r = Runner(cfg, DomainRegistry(cfg), ws, None, reg)
    calls = [{"name": "grep", "arguments": {}},
             {"name": "write_file", "arguments": {}},
             {"name": "glob", "arguments": {}}]
    logs = []
    r._execute_tool_calls_batch(calls, reg.list(), logs, unit_id="U")
    seq = [x for x in order if x != "|"]
    assert seq[0] == "grep" and seq[-1] == "glob", f"屏障区间错误：{seq}"
    assert seq.index("write-start") > 0 and seq.index("write-end") == len(seq) - 2, \
        f"写必须位于两个读之间（不在任一读批内并发）：{seq}"
