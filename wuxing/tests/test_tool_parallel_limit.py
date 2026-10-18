"""TDD：工具并发控制（#3 用户要点）——单碎片批量并发上限（默认 8/硬 10）。

背景：单轮全方案时碎片×工具并发会失控——工具批量原为无上限起线程；
全局上界 = max_parallel_units × max_parallel_tools（确定性有界）。
"""
import pathlib
import tempfile
import threading
import time

from wuxing.config import EngineConfig
from wuxing.protocols import Tool, ToolResult
from wuxing.registry import DomainRegistry
from wuxing.runner import MAX_PARALLEL_TOOLS, Runner
from wuxing.tools.base import ToolRegistry
from wuxing.workspace import Workspace


class _ProbeReadTool(Tool):
    """read_file 替身：记录同时在跑的调用数（确定性并发证据）。"""

    def __init__(self, state):
        self.state = state

    def name(self):
        return "read_file"

    def description(self):
        return "probe"

    def input_schema(self):
        return {"type": "object", "properties": {"path": {"type": "string"}}}

    def permission(self):
        return {"read": True, "write": False, "execute": False,
                "network": False, "destructive": False}

    def execute(self, path="", **kw):
        with self.state["lock"]:
            self.state["active"] += 1
            self.state["max"] = max(self.state["max"], self.state["active"])
        try:
            b = self.state.get("barrier")
            if b is not None:
                b.wait(timeout=3)  # 4 个调用必须真正同时在跑
            else:
                time.sleep(0.05)
        finally:
            with self.state["lock"]:
                self.state["active"] -= 1
        return ToolResult(status="ok", content="ok", tool_name="read_file")


def _mk_runner(state, limit):
    cfg = EngineConfig()
    cfg.max_parallel_tools = limit
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    reg = ToolRegistry([_ProbeReadTool(state)])
    return Runner(cfg, DomainRegistry(cfg), ws, None, reg)


def test_tool_batch_workers_capped():
    """12 个读类调用：并发必须恰好 = 上限 4（Barrier(4) 确定性口径）。"""
    state = {"lock": threading.Lock(), "active": 0, "max": 0}
    state["barrier"] = threading.Barrier(4)
    r = _mk_runner(state, 4)
    r._read_ok = False
    r._write_ok = False
    r._deliverables = []
    batch = [{"name": "read_file", "arguments": {"path": f"f{i}.txt"}}
             for i in range(12)]
    r._execute_tool_calls_batch(batch, r.tools.filter(("read_file",)), [])
    assert state["max"] == 4, f"并发必须恰为上限 4（实际 {state['max']}）"


def test_tool_parallel_hard_cap_is_10():
    assert MAX_PARALLEL_TOOLS == 10
    from wuxing.orchestrator import MAX_PARALLEL_UNITS
    # 全局上界 = 单元并行 × 单碎片工具并行（确定性有界——用户要点）
    assert MAX_PARALLEL_UNITS == 10
