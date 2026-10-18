from wuxing.llm.tool_client import ToolCallingLlm


class FakeLlm:
    def __init__(self, reply):
        self.reply = reply
        self.call_count = 0
    def name(self): return "fake"
    def chat(self, messages, tools=None):
        self.call_count += 1
        return self.reply

def test_toolcall_llm_injects_tool_schemas():
    llm = ToolCallingLlm(FakeLlm("ok"), tools_desc=lambda: [
        {"name": "read_file", "description": "读取文件", "input_schema": {"type": "object"}}])
    out = llm.chat([{"role": "user", "content": "读文件"}])
    assert out.text == "ok"
    assert llm.call_count == 1

def test_toolcall_llm_system_prompt_contains_schema():
    class RecordingLlm:
        def __init__(self): self.seen = None
        def name(self): return "rec"
        def chat(self, messages):  # 不支持 tools 参数 → 触发文本协议回退
            self.seen = messages
            return "done"
    inner = RecordingLlm()
    llm = ToolCallingLlm(inner, tools_desc=lambda: [
        {"name": "bash", "description": "执行命令", "input_schema": {"type": "object"}}])
    llm.chat([{"role": "user", "content": "跑一下"}])
    system = inner.seen[0]
    assert system["role"] == "system"
    assert "TOOLCALL:" in system["content"]
    assert "bash" in system["content"]
