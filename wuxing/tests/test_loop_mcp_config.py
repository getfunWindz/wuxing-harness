"""TDD · L2-1：MCP 配置面——config.jsonc → 引擎可见 MCP 工具（审查 A3 闭合）。

权限纪律：未声明 permissions 的工具默认拦截（最小权限——「显式解锁」）。
端到端：mini FastMCP server（stdio）→ load_mcp_tools → 引擎装配 → execute。
"""
import pathlib
import sys
import tempfile

from wuxing.config import EngineConfig
from wuxing.engine import Engine
from wuxing.tools.mcp_bridge import McpServerConfig

_SERVER = str(pathlib.Path(__file__).with_name("mcp_echo_server.py"))


def _mcp_cfg(permissions=None):
    return McpServerConfig(
        name="echo", command=sys.executable, args=[_SERVER],
        permissions=permissions)


def test_engine_loads_mcp_tools_from_config():
    """L2-1：EngineConfig.mcp_servers → 引擎工具可见（配置面接线——此前死路径）。"""
    cfg = EngineConfig(mcp_servers=[{
        "name": "echo", "command": sys.executable, "args": [_SERVER]}])
    eng = Engine(cfg=cfg, workdir=pathlib.Path(tempfile.mkdtemp()),
                 auto_confirm=True)
    t = eng.tools.get("mcp__echo__echo")
    assert t is not None, "MCP 工具必须经配置装载进引擎（配置面未接线）"
    assert t.description() == "回声工具：返回输入文本（端到端验证工具调用链）。"


def test_mcp_tool_blocked_without_permission_declaration():
    """L2-1：未声明 permissions → 默认拦截（最小权限——显式解锁哲学）。"""
    cfg = EngineConfig(mcp_servers=[{
        "name": "echo", "command": sys.executable, "args": [_SERVER]}])
    eng = Engine(cfg=cfg, workdir=pathlib.Path(tempfile.mkdtemp()),
                 auto_confirm=True)
    res = eng.tools.execute("mcp__echo__echo", text="hi")
    assert res.status == "blocked", "未声明权限必须被拦（permission 声明制）"


def test_mcp_tool_works_after_permission_declared():
    """L2-1：显式声明权限后工具可执行（端到端调用链完整）。"""
    cfg = EngineConfig(mcp_servers=[{
        "name": "echo", "command": sys.executable, "args": [_SERVER],
        "permissions": {"read": True, "write": False, "execute": True,
                        "network": False, "destructive": False}}])
    eng = Engine(cfg=cfg, workdir=pathlib.Path(tempfile.mkdtemp()),
                 auto_confirm=True)
    res = eng.tools.execute("mcp__echo__echo", text="hello")
    assert res.status == "ok", res.error
    assert res.content == "echo: hello"


def test_mcp_tool_reachable_in_runner_whitelist():
    """A5 复现：MCP 工具在 Runner 路径必须可达——域白名单闸对 MCP 是死闸
    （is_mcp 工具按 mcp:* 前缀语义放行；未声明 permissions 仍被 Registry 拦——双闸）。"""
    cfg = EngineConfig(mcp_servers=[{
        "name": "echo", "command": sys.executable, "args": [_SERVER],
        "permissions": {"read": True, "write": False, "execute": True,
                        "network": False, "destructive": False}}])
    eng = Engine(cfg=cfg, workdir=pathlib.Path(tempfile.mkdtemp()),
                 auto_confirm=True)

    class McpCallingLlm:
        def __init__(self):
            self.usage_history = []
            self.call_count = 0

        def name(self):
            return "mcp-caller"

        def spec(self):
            return "mcp-caller"

        def supports_native_tools(self):
            return False

        def chat(self, messages, tools=None):
            self.usage_history.append({"input": 10, "output": 5,
                                       "cache_read": 0, "cache_write": 0})
            # A1 后 execute 域需写物证——先写产物再调 MCP（文本协议多行 TOOLCALL）
            return ("TOOLCALL:write_artifact path=out.md kind=result content=已处理\n"
                    "TOOLCALL:mcp__echo__echo text=hello\n执行完成")

    eng.llm = McpCallingLlm()
    res = eng.orchestrator.runner.run_unit(
        "F-x", "execute",
        {"goal": "调用 echo", "task": "调用 echo", "plan": "x",
         "result": "", "paths": "", "fragment_key": "调用 echo"})
    assert res.status == "ok", f"MCP 工具经白名单闸应可达：{res.error}"
    assert not any("not in whitelist" in l for l in res.logs), \
        f"MCP 工具不得被白名单拦截：{res.logs}"


def test_mcp_unpermissioned_still_blocked_by_registry():
    """对照：未声明 permissions 的 MCP 工具即便白名单放行，仍被权限闸拦截（最小权限）。"""
    cfg = EngineConfig(mcp_servers=[{
        "name": "echo", "command": sys.executable, "args": [_SERVER]}])
    eng = Engine(cfg=cfg, workdir=pathlib.Path(tempfile.mkdtemp()),
                 auto_confirm=True)
    res = eng.tools.execute("mcp__echo__echo", text="hi")
    assert res.status == "blocked", "未声明权限必须被拦（permission 声明制）"
    assert "permission" in (res.error or ""), res.error


def test_mcp_server_specific_whitelist_entry():
    """白名单前缀语义：mcp:{server} 条目匹配该 server 全部工具（server 级显式解锁）。"""
    from wuxing.tools.base import whitelist_accepts
    assert whitelist_accepts("mcp__echo__echo", ("mcp:*",), is_mcp=True)
    assert whitelist_accepts("mcp__echo__echo", ("mcp:echo",), is_mcp=True)
    assert whitelist_accepts("mcp__echo__echo", ("mcp:echo", "write_artifact"), is_mcp=True)
    assert not whitelist_accepts("mcp__echo__echo", ("mcp:other",), is_mcp=True)
    assert not whitelist_accepts("mcp__echo__echo", ("write_artifact",), is_mcp=True)
    # 非 MCP 工具不受 mcp: 前缀条目影响
    assert not whitelist_accepts("write_artifact", ("mcp:*",), is_mcp=False)


def test_bad_mcp_server_does_not_crash_engine():
    """A5：MCP server 启动失败不得拖垮引擎——坏工具不坏引擎（逐 server 降级跳过）。"""
    cfg = EngineConfig(mcp_servers=[
        # 正常 server（声明权限）
        {"name": "echo", "command": sys.executable, "args": [_SERVER],
         "permissions": {"read": True, "write": False, "execute": True,
                         "network": False, "destructive": False}},
        # 坏 server：命令不存在——必须降级跳过而非构造崩溃
        {"name": "bad", "command": "wuxing-nonexistent-cmd-xyz-123",
         "args": [], "permissions": {"read": True}}])
    eng = Engine(cfg=cfg, workdir=pathlib.Path(tempfile.mkdtemp()),
                 auto_confirm=True)
    assert eng.tools.get("mcp__echo__echo") is not None, \
        "正常 server 工具必须仍装载（降级只跳过坏 server）"


def test_config_validation_rejects_bad_mcp_entry():
    """配置校验：mcp_servers 条目缺 name/command → 非法（早报——字段级定位）。"""
    from wuxing.config_schema import validate_config
    errors = validate_config({"mcp_servers": [
        {"command": "x"}, {"name": "s", "command": ""}]})
    assert any("mcp_servers[0].name" in e for e in errors)
    assert any("mcp_servers[1].command" in e for e in errors)
    assert validate_config({"mcp_servers": [{"name": "echo",
                                             "command": "python"}]}) == []


def test_mcp_server_env_whitelist_passthrough():
    """E4：McpServerConfig.env 白名单字段——server 依赖环境变量场景可显式声明
    （值=环境变量名：机密不进配置——运行时从 os.environ 解析；未声明=不注入）。"""
    import os

    from wuxing.tools.mcp_bridge import McpServerConfig, _env_for
    os.environ["WUXING_TEST_MCP_TOKEN"] = "real-secret-123"
    cfg = McpServerConfig(name="s", command="x",
                          env={"MY_TOKEN": "WUXING_TEST_MCP_TOKEN"})
    env = _env_for(cfg)
    assert env["MY_TOKEN"] == "real-secret-123", \
        "env 声明按环境变量名解析（机密不进配置——运行时读取）"
    # 未声明 env → 仅擦洗后的本机环境（R3-2 升级：机密剔除——不再 None/全继承）
    cfg2 = McpServerConfig(name="s2", command="x")
    env2 = _env_for(cfg2)
    assert env2 is not None and "PATH" in env2
    assert "WUXING_TEST_MCP_TOKEN" not in env2   # TOKEN 后缀 → 已擦洗
