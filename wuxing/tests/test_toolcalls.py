from wuxing.llm.tool_client import ToolCallingLlm
from wuxing.llm.tool_results import ToolCallResult


class FakeLlm:
    def __init__(self):
        self.last_messages = None
        self.last_tools = None
    def name(self): return "fake"
    def chat(self, messages, tools=None):
        self.last_messages = messages
        self.last_tools = tools
        return ToolCallResult(
            text="我需要读取文件",
            tool_calls=[{"name": "read_file", "arguments": {"path": "a.txt"}}])

def test_toolcall_llm_returns_structured():
    llm = ToolCallingLlm(FakeLlm(), tools_desc=lambda: [
        {"name": "read_file", "description": "d", "input_schema": {"type": "object"}}])
    result = llm.chat([{"role": "user", "content": "读 a.txt"}])
    assert isinstance(result, ToolCallResult)
    assert result.text == "我需要读取文件"
    assert result.tool_calls[0]["name"] == "read_file"

def test_toolcall_llm_passes_native_tools_param():
    llm = ToolCallingLlm(FakeLlm(), tools_desc=lambda: [
        {"name": "read_file", "description": "d", "input_schema": {"type": "object"}}])
    llm.chat([{"role": "user", "content": "x"}])
    inner = llm._inner
    assert inner.last_tools is not None
    assert inner.last_tools[0]["function"]["name"] == "read_file"

def test_toolcall_text_only():
    class TextOnly:
        def name(self): return "text"
        def chat(self, messages, tools=None):
            return ToolCallResult(text="完成", tool_calls=[])
    llm = ToolCallingLlm(TextOnly(), tools_desc=list)
    r = llm.chat([{"role": "user", "content": "x"}])
    assert r.tool_calls == []
    assert r.text == "完成"
