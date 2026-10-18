"""TDD：#3 重复调用治理——单元内同名同参计数（第 3 次提醒一次，不阻断）。

依据：报告 #6——同名同参重复 427/941（45.4%，含大量跨轮非连续空转）；
原「连续 ≥3 次」检测漏掉非连续重复。原则：只提示，不阻断（模型自主决策）。
"""
import pathlib
import tempfile

from wuxing.config import EngineConfig
from wuxing.llm.mock import MockLlmProvider
from wuxing.registry import DomainRegistry
from wuxing.runner import Runner
from wuxing.tools.loader import load_tools
from wuxing.workspace import Workspace


def test_repeat_tool_call_unit_scope_warn_once():
    """第 3 次相同调用（含非连续）提醒一次；第 4 次不再刷屏。"""
    cfg = EngineConfig()
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    r = Runner(cfg, DomainRegistry(cfg), ws, MockLlmProvider(), load_tools(ws))
    # _execute_toolcall 直接调用：补 run_unit 内初始化的物证字段
    # （否则写工具路径 AttributeError——测试夹具配置，非生产路径）
    r._write_ok = False
    r._read_ok = False
    r._deliverables = []
    tc = {"name": "write_artifact",
          "arguments": {"path": "a.md", "kind": "result", "content": "x"}}
    wl = r.tools.filter(("write_artifact", "read_file", "write_file", "bash"))
    outs = [r._execute_toolcall(tc, wl, unit_id="U-1") for _ in range(4)]
    assert not any("[warn]" in x for x in outs[0] + outs[1]), "前两次不提醒"
    assert any("第 3 次" in x for x in outs[2]), "第 3 次必须提醒一次"
    assert not any("[warn]" in x for x in outs[3]), "第 4 次不重复刷屏"


def test_repeat_guard_reset_per_unit():
    """单元内计数不跨单元泄漏（新单元从零计）。"""
    cfg = EngineConfig()
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    r = Runner(cfg, DomainRegistry(cfg), ws, MockLlmProvider(), load_tools(ws))
    r._write_ok = False
    r._read_ok = False
    r._deliverables = []
    tc = {"name": "write_artifact",
          "arguments": {"path": "b.md", "kind": "result", "content": "y"}}
    wl = r.tools.filter(("write_artifact",))
    r._tool_key_counts = {}  # 模拟 run_unit 初始化
    r._execute_toolcall(tc, wl, unit_id="U-1")
    r._execute_toolcall(tc, wl, unit_id="U-1")
    r._tool_key_counts = {}  # 新单元重置
    out = r._execute_toolcall(tc, wl, unit_id="U-2")
    assert not any("[warn]" in x for x in out), "新单元必须重新计数"


def test_repeat_counter_supports_structured_args():
    """六轮审查 A1：工具参数含 list/dict（MCP 数组/对象 schema）时，
    重复计数不得因不可哈希而崩溃——原实现 tuple(sorted(kwargs.items()))
    对 list 参数抛 TypeError: unhashable type（可拖垮整个任务运行）。"""
    from wuxing.protocols import Tool, ToolResult
    from wuxing.tools.base import ToolRegistry

    class _ProbeArrayTool(Tool):
        def name(self):
            return "mcp_probe"

        def description(self):
            return "probe"

        def input_schema(self):
            return {"type": "object", "properties": {
                "tags": {"type": "array"}, "meta": {"type": "object"}}}

        def permission(self):
            return {"read": True, "write": False, "execute": False,
                    "network": False, "destructive": False}

        def execute(self, tags=None, meta=None, **kw):
            return ToolResult(status="ok", content="ok", tool_name="mcp_probe")

    cfg = EngineConfig()
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    r = Runner(cfg, DomainRegistry(cfg), ws, MockLlmProvider(),
               ToolRegistry([_ProbeArrayTool()]))
    r._write_ok = False
    r._read_ok = False
    r._deliverables = []
    tc = {"name": "mcp_probe", "arguments": {"tags": ["a", "b"],
                                          "meta": {"k": [1, 2]}}}
    wl = [_ProbeArrayTool()]
    outs = [r._execute_toolcall(tc, wl, unit_id="U-1") for _ in range(4)]
    assert not any("[warn]" in x for x in outs[1]), "第 2 次不提醒"
    assert any("第 3 次" in x for x in outs[2]), \
        "结构化参数同样触发第 3 次提醒（计数语义不因参数类型改变）"
