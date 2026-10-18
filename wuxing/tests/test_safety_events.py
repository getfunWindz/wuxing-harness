"""TDD：安全拦截事件（壳 UI 阶段 4 · 引擎对齐项⑪）。

- danger_guard.check_command：返回拦截原因（透出给事件/界面）
- ToolRegistry：guard 返回原因串 → 拦截结果携带原因
- Runner：blocked 工具调用 → 发出 SafetyBlocked 事件（流内警示卡数据源）
"""
import pathlib
import tempfile


def test_check_command_returns_reason():
    from wuxing.danger_guard import check_command
    assert check_command("sudo apt install x") == "提权命令"
    assert check_command("rm -rf /") == "根/盘符/家目录删除"
    assert check_command("echo ok") is None


def test_guard_reason_flows_into_blocked_result():
    from wuxing.danger_guard import check_command
    from wuxing.tools.base import ToolRegistry
    from wuxing.tools.bash_tool import BashTool
    from wuxing.workspace import Workspace
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    reg = ToolRegistry([BashTool(ws)])
    reg.set_guard(lambda name, kwargs: (
        (check_command(kwargs.get("command", "")) or True)
        if name == "bash" else True))
    out = reg.execute("bash", command="rm -rf /")
    assert out.status == "blocked"
    assert "根/盘符" in out.error, out.error
    out2 = reg.execute("bash", command="sudo apt install x")
    assert out2.status == "blocked"
    assert "提权命令" in out2.error, out2.error


def test_runner_emits_safety_blocked_event():
    from wuxing.config import EngineConfig
    from wuxing.danger_guard import check_command
    from wuxing.runner import Runner
    from wuxing.tools.base import ToolRegistry
    from wuxing.tools.bash_tool import BashTool
    from wuxing.workspace import Workspace
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    cfg = EngineConfig()
    reg = ToolRegistry([BashTool(ws)])
    reg.set_guard(lambda name, kwargs: (
        (check_command(kwargs.get("command", "")) or True)
        if name == "bash" else True))
    runner = Runner(cfg, None, ws, None, reg)
    events = []
    runner.emit_event = events.append
    runner._execute_toolcall(
        {"name": "bash", "arguments": {"command": "sudo rm -rf /"}},
        [reg.get("bash")], unit_id="U-1")
    blocked = [e for e in events if type(e).__name__ == "SafetyBlocked"]
    assert blocked, [type(e).__name__ for e in events]
    ev = blocked[0]
    assert ev.tool == "bash" and "sudo" in ev.command
    assert ev.reason, "拦截原因必填写入事件"
    assert ("提权命令" in ev.reason) or ("根/盘符" in ev.reason), ev.reason


def test_mcp_permission_block_emits_safety_event():
    """MCP 权限未声明（最小权限默认拒绝）→ 同类 SafetyBlocked 事件。"""
    from wuxing.config import EngineConfig
    from wuxing.runner import Runner
    from wuxing.tools.base import ToolRegistry
    from wuxing.workspace import Workspace

    class NoPermTool:
        is_mcp = True
        def name(self): return "mcp_demo_tool"
        def description(self): return "demo"
        def input_schema(self): return {"type": "object"}
        def permission(self): return {}          # 未声明 → 默认拒绝
        def execute(self, **kwargs): return "never"

    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    reg = ToolRegistry([NoPermTool()])
    runner = Runner(EngineConfig(), None, ws, None, reg)
    events = []
    runner.emit_event = events.append
    runner._execute_toolcall({"name": "mcp_demo_tool", "arguments": {}},
                             [reg.get("mcp_demo_tool")], unit_id="U-2")
    blocked = [e for e in events if type(e).__name__ == "SafetyBlocked"]
    assert blocked and "permission" in blocked[0].reason, [e for e in events]
