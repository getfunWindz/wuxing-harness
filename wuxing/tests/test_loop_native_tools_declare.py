"""TDD · L4/GLM 差分发现：原生 tools 能力声明分层——文本协议说明仅对不支持原生的 provider 注入。

证据（GLM 会话回放）：同时给 tools schema + TOOLCALL 文本说明 = 双轨诱导——
GLM 混用（轮 4 输出文本 TOOLCALL + 中文参数名 路径= → schema 拒绝 → 预算耗尽）。
"""
import pathlib
import tempfile

from wuxing.config import EngineConfig
from wuxing.registry import DomainRegistry
from wuxing.runner import Runner
from wuxing.tools.builtin import BUILTIN_TOOLS
from wuxing.workspace import Workspace


class _NativeLlm:
    """声明原生 tools 支持（OpenAI/Anthropic 系真实 provider）。"""

    def supports_native_tools(self):
        return True

    def name(self):
        return "native"

    def chat(self, messages, tools=None):
        return "x"


class _TextLlm:
    """无原生支持（mock/旧走文本协议）。"""

    def supports_native_tools(self):
        return False

    def name(self):
        return "text"

    def chat(self, messages, tools=None):
        return "x"


def _sys(llm):
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    probe = llm
    if probe.chat.__self__ is None:
        pass
    # 包装记录 seen
    class W:
        def __init__(s):
            s.seen = []
        def name(s):
            return probe.name()
        def supports_native_tools(s):
            return probe.supports_native_tools()
        def chat(s, messages, tools=None):
            s.seen.append([dict(m) for m in messages])
            return probe.chat(messages, tools)
    w = W()
    Runner(EngineConfig(), DomainRegistry(EngineConfig()), ws, w,
           BUILTIN_TOOLS(ws)).run_unit("U-1", "plan", {"goal": "g"})
    return w.seen[0][0]["content"]


def test_native_provider_no_text_protocol_instruct():
    """原生 provider：system 不得含 TOOLCALL 文本协议说明（双轨诱导根因）。"""
    sys_text = _sys(_NativeLlm())
    assert "TOOLCALL:" not in sys_text, \
        "原生 tools 下系统提示不得教文本协议（模型混用=参数名中文错配）"


def test_text_provider_keeps_text_protocol_instruct():
    """非原生 provider：保留 TOOLCALL 说明（文本协议兜底路径。）。"""
    sys_text = _sys(_TextLlm())
    assert "TOOLCALL:" in sys_text, "文本协议 provider 需说明（兜底）"
