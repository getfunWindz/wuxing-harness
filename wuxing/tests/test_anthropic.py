from wuxing.llm.anthropic import AnthropicProvider


class FakeResp:
    def __init__(self, content): self._c = content
    def raise_for_status(self): pass
    def json(self): return self._c

def _kw_headers(calls):
    return str(calls.get("headers", {}))

def test_anthropic_messages_api():
    calls = {}
    class Http:
        def post(self, url, **kw):
            calls["url"] = url; calls["body"] = kw["json"]; calls["headers"] = kw["headers"]
            return FakeResp({"content": [{"type": "text", "text": "claude-ok"}]})
    p = AnthropicProvider(api_key="k", _http=Http())
    assert p.chat([{"role": "user", "content": "hi"}]) == "claude-ok"
    assert "anthropic-version" in _kw_headers(calls)
    assert calls["url"].endswith("/messages")
    assert calls["body"]["model"] == "claude-sonnet-4-5"

def test_anthropic_system_split():
    calls = {}
    class Http:
        def post(self, url, **kw):
            calls["body"] = kw["json"]
            return FakeResp({"content": [{"type": "text", "text": "x"}]})
    p = AnthropicProvider(api_key="k", _http=Http())
    p.chat([{"role": "system", "content": "你是助手"}, {"role": "user", "content": "hi"}])
    body = calls["body"]
    # P1 T2：system 为 cache_control block 数组（稳定前缀接线）
    assert body["system"][0]["text"] == "你是助手"
    assert body["system"][0]["cache_control"]["type"] == "ephemeral"
    assert all(m["role"] != "system" for m in body["messages"])


# ============================== L0-2 原生 tools 接线 ==========================
from wuxing.llm.tool_results import ToolCallResult

_OPENAI_TOOLS = [{"type": "function", "function": {
    "name": "write_artifact", "description": "写产物",
    "parameters": {"type": "object", "properties": {"path": {"type": "string"}},
                   "required": ["path"]}}}]


def test_anthropic_tools_payload_converted():
    """L0-2：tools 参数必须转换为 Anthropic 格式进入 payload（此前被忽略=纯文本协议）。
    OpenAI 兼容格式（type/function 包装）→ {name, description, input_schema}。"""
    calls = {}
    class Http:
        def post(self, url, **kw):
            calls["body"] = kw["json"]
            return FakeResp({"content": [{"type": "text", "text": "x"}]})
    p = AnthropicProvider(api_key="k", _http=Http())
    p.chat([{"role": "user", "content": "hi"}], tools=_OPENAI_TOOLS)
    tools = calls["body"].get("tools")
    assert tools is not None, "payload 必须含 tools（原生工具调用接线）"
    assert tools[0]["name"] == "write_artifact"
    assert tools[0]["description"] == "写产物"
    assert tools[0]["input_schema"]["required"] == ["path"]
    assert "function" not in tools[0], "Anthropic 格式无 type/function 包装"


def test_anthropic_tool_use_returned_structured():
    """L0-2：tool_use block → ToolCallResult（text + tool_calls 结构化）。"""
    calls = {}
    class Http:
        def post(self, url, **kw):
            calls["body"] = kw["json"]
            return FakeResp({"content": [
                {"type": "text", "text": "我先写"},
                {"type": "tool_use", "id": "tu_1", "name": "write_artifact",
                 "input": {"path": "p.md", "content": "x"}}]})
    p = AnthropicProvider(api_key="k", _http=Http())
    out = p.chat([{"role": "user", "content": "hi"}], tools=_OPENAI_TOOLS)
    assert isinstance(out, ToolCallResult)
    assert out.text == "我先写"
    assert out.tool_calls == [{"name": "write_artifact",
                               "arguments": {"path": "p.md", "content": "x"}}]


def test_anthropic_plain_text_still_string():
    """L0-2：无 tool_use 时保持 str 返回（不破坏现有消费路径）。"""
    p = AnthropicProvider(api_key="k", _http=type(
        "_H", (), {"post": lambda self, url, **kw: FakeResp(
            {"content": [{"type": "text", "text": "ok"}]})})())
    assert p.chat([{"role": "user", "content": "hi"}]) == "ok"


def test_anthropic_tools_last_item_cache_control():
    """Pi 同款（用户裁决）：Anthropic tools 数组**最后一项**打 cache_control——
    工具定义整段进缓存（system 断点之外的工具段断点）。"""
    from wuxing.llm.anthropic import AnthropicProvider

    p = AnthropicProvider(model="claude-sonnet-4-5", api_key="x", _http=object())
    tools = [
        {"type": "function", "function": {"name": "a", "description": "A",
                                          "parameters": {"type": "object"}}},
        {"type": "function", "function": {"name": "b", "description": "B",
                                          "parameters": {"type": "object"}}},
    ]
    out = p._to_anthropic_tools(tools)
    assert len(out) == 2
    assert "cache_control" not in out[0], "非末项不打（缓存断点=最后一个）"
    assert out[1].get("cache_control") == {"type": "ephemeral"}, \
        "tools 最后一项必须打 cache_control（Pi 同款）"


def test_anthropic_tools_single_item_cache_control():
    """单工具也要打（最后一项=第一项）。"""
    from wuxing.llm.anthropic import AnthropicProvider
    p = AnthropicProvider(model="m", api_key="x", _http=object())
    out = p._to_anthropic_tools([
        {"type": "function", "function": {"name": "a", "description": "A",
                                          "parameters": {}}}])
    assert out[0].get("cache_control") == {"type": "ephemeral"}


def test_anthropic_usage_input_unified_total_prompt():
    """B 级修复：Anthropic input_tokens 不含 cache 读写——usage.input 统一为
    总输入（input+creation+read，与 DeepSeek prompt_tokens 口径一致）——
    否则 cache_read_ratio 可 >1、成本估算可为负（多通道真实测试口径）。"""
    class Http:
        def post(self, url, **kw):
            return FakeResp({
                "content": [{"type": "text", "text": "ok"}],
                "usage": {"input_tokens": 100, "output_tokens": 10,
                          "cache_read_input_tokens": 900,
                          "cache_creation_input_tokens": 50}})
    p = AnthropicProvider(api_key="k", _http=Http())
    p.chat([{"role": "user", "content": "hi"}])
    u = p.usage_history[-1]
    assert u["input"] == 1050, "input 必须是总输入（100+900+50）"
    assert u["cache_read"] == 900
    assert u["cache_write"] == 50
    assert u["input"] >= u["cache_read"], "命中率口径 = read/input 必须 ≤1"
