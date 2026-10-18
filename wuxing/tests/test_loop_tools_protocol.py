"""TDD：真 LLM 冒烟暴露的协议层缺口（F1/F2——工具调用的可达性）。

冒烟实证：真 LLM 从不调用工具（execute 把代码写进文本）——runner 调
chat(messages) 未传原生 tools；system 无 TOOLCALL 语法说明。mock 直接返回
ToolCallResult 绕过协议层 → 测试全绿掩盖（知识库「假阳性陷阱」实证）。
"""
import pathlib
import tempfile

from wuxing.config import EngineConfig
from wuxing.llm.tool_results import ToolCallResult
from wuxing.registry import DomainRegistry
from wuxing.runner import Runner
from wuxing.tools.loader import load_tools
from wuxing.workspace import Workspace


class ToolsAwareLlm:
    """记录是否收到 tools 参数的假 LLM（模拟真 provider 的原生工具路径）。"""

    def __init__(self):
        self.seen_tools = None

    def name(self):
        return "toolsaware"

    def chat(self, messages, tools=None):
        self.seen_tools = tools
        # 原生工具路径：收到 tools → 返回 tool_calls（像真 LLM 那样调工具）
        if tools:
            return ToolCallResult(text="方案：完整执行计划", tool_calls=[
                {"name": "write_artifact",
                 "arguments": {"path": "p.md", "kind": "plan", "content": "x"}}])
        return "方案：完整执行计划"


def test_runner_passes_native_tools_to_llm():
    """F1：runner 必须把白名单工具以原生 schema 传给 LLM（工具可达性）。"""
    llm = ToolsAwareLlm()
    cfg = EngineConfig(max_loop_rounds=6, max_unit_budget=3)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    r = Runner(cfg, DomainRegistry(cfg), ws, llm, load_tools(ws))
    res = r.run_unit("U-1", "plan", {"goal": "plan:x"})
    assert res.status == "ok"
    assert llm.seen_tools is not None, "LLM 必须收到原生 tools（否则真模型不知可调工具）"
    names = [t["function"]["name"] for t in llm.seen_tools]
    assert "write_artifact" in names, f"白名单工具必须在 schema 中：{names}"
    assert all(t["type"] == "function"
               and "parameters" in t["function"] for t in llm.seen_tools), \
        f"schema 结构必须规范：{llm.seen_tools}"


class LegacyLlm:
    """旧假 LLM（chat 无 tools 参数）——兼容回退路径。"""

    def name(self):
        return "legacy"

    def chat(self, messages):
        return "方案：完整执行计划"


def test_legacy_llm_without_tools_param_still_works():
    """F1 回退：LLM.chat 不接受 tools 参数 → 不崩（旧假 LLM/文本协议兜底）。"""
    llm = LegacyLlm()
    cfg = EngineConfig(max_loop_rounds=6, max_unit_budget=3)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    r = Runner(cfg, DomainRegistry(cfg), ws, llm, load_tools(ws))
    res = r.run_unit("U-1", "plan", {"goal": "plan:x"})
    assert res.status == "ok"


def test_system_prompts_toolcall_syntax():
    """F2（L4 修正）：原生 tools 探针（收 tools 即原生调用）——能力分层后

    system 不得含文本 TOOLCALL 说明（双轨诱导消除）；非原生兜底见

    test_loop_native_tools_declare。"""
    llm = ToolsAwareLlm()
    cfg = EngineConfig(max_loop_rounds=6, max_unit_budget=3)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    r = Runner(cfg, DomainRegistry(cfg), ws, llm, load_tools(ws))
    r.run_unit("U-1", "plan", {"goal": "plan:x"})
    assert llm.seen_tools is not None  # 原生 tools 已接线
    system_text = r._messages[0]["content"]
    assert "TOOLCALL" not in system_text, "原生 provider 不得教文本协议（双轨诱导）"
