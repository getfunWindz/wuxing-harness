from wuxing.llm.openai import OpenAIChatProvider, OpenAIResponsesProvider


class FakeResp:
    def __init__(self, content): self._c = content
    def raise_for_status(self): pass
    def json(self): return self._c

def test_openai_chat_compatible():
    calls = {}
    class Http:
        def post(self, url, **kw):
            calls["url"] = url
            calls["body"] = kw["json"]
            return FakeResp({"choices": [{"message": {"content": "hi-oa"}}]})
    p = OpenAIChatProvider(base_url="https://example.com/v1", api_key="k", _http=Http())
    assert p.chat([{"role": "user", "content": "x"}]) == "hi-oa"
    assert calls["url"].endswith("/chat/completions")
    assert calls["body"]["model"] == "deepseek-chat"  # 默认模型

def test_openai_chat_retries_temperature():
    class Flaky:
        def __init__(self): self.n = 0
        def post(self, url, **kw):
            self.n += 1
            if self.n == 1:
                import requests
                raise requests.ConnectionError()
            return FakeResp({"choices": [{"message": {"content": "ok"}}]})
    p = OpenAIChatProvider(api_key="k", _http=Flaky(), max_retries=2)
    assert p.chat([{"role": "user", "content": "x"}]) == "ok"

def test_responses_api():
    calls = {}
    class Http:
        def post(self, url, **kw):
            calls["url"] = url; calls["body"] = kw["json"]
            return FakeResp({"output": [{"content": [{"type": "output_text", "text": "resp-ok"}]}]})
    p = OpenAIResponsesProvider(api_key="k", _http=Http())
    assert p.chat([{"role": "user", "content": "x"}]) == "resp-ok"
    assert "/responses" in calls["url"]

def test_responses_uses_streaming_fallback():
    class Http:
        def post(self, url, **kw):
            return FakeResp({"output": [{"content": []}]})
    p = OpenAIResponsesProvider(api_key="k", _http=Http())
    assert p.chat([{"role": "user", "content": "x"}]) != ""


def test_responses_sends_tools_flat_and_parses_function_calls():
    """黄金测试阻断修复（2026-09-30）：Responses 适配器必须支持工具面——

    旧实现 `chat(messages)` 无 tools 参数 → 引擎降级为无工具调用 →
    模型只能输出 DSML 文本（无法写文件/执行）→ 契约永假空转（用户实测灾难）。
    纪律：Responses 工具格式为**扁平**（name/description/parameters 顶层，
    不同于 chat-completions 的嵌套 function）。
    """
    calls = {}

    class Http:
        def post(self, url, headers=None, json=None, timeout=None):
            calls["payload"] = json
            return FakeResp({"output": [
                {"type": "function_call", "name": "write_file",
                 "arguments": '{"path": "a.txt", "content": "x"}',
                 "call_id": "c1"},
                {"type": "message", "content": [
                    {"type": "output_text", "text": "我来写文件"}]},
            ]})

    p = OpenAIResponsesProvider(api_key="k", _http=Http())
    tools = [{"type": "function", "function": {
        "name": "write_file", "description": "写文件",
        "parameters": {"type": "object", "properties": {}}}}]
    out = p.chat([{"role": "user", "content": "x"}], tools=tools)
    assert calls["payload"]["tools"] == [
        {"type": "function", "name": "write_file", "description": "写文件",
         "parameters": {"type": "object", "properties": {}}}]
    from wuxing.llm.tool_results import ToolCallResult
    assert isinstance(out, ToolCallResult)
    assert out.tool_calls[0]["name"] == "write_file"
    assert out.tool_calls[0]["arguments"] == {"path": "a.txt", "content": "x"}
    assert "我来写文件" in out.text
    # 无 tools → 不携带字段（向后兼容）
    p.chat([{"role": "user", "content": "x"}])
    assert "tools" not in calls["payload"]


def test_responses_parses_usage_and_reasoning():
    """黄金测试阻断修复：usage（含缓存命中/思维链 token）与 reasoning 摘要必须解析。"""
    class Http:
        def post(self, url, headers=None, json=None, timeout=None):
            return FakeResp({
                "output": [
                    {"type": "reasoning", "summary": [
                        {"type": "summary_text", "text": "先分析需求"}]},
                    {"type": "message", "content": [
                        {"type": "output_text", "text": "ok"}]},
                ],
                "usage": {"input_tokens": 1000, "output_tokens": 50,
                          "input_tokens_details": {"cached_tokens": 800},
                          "output_tokens_details": {"reasoning_tokens": 30}},
            })

    p = OpenAIResponsesProvider(api_key="k", _http=Http())
    assert p.chat([{"role": "user", "content": "x"}]) == "ok"
    u = p.usage_history[-1]
    assert u["input"] == 1000, "input_tokens 必须记录（完整 prompt 量口径）"
    assert u["cache_read"] == 800, "cached_tokens 必须解析（缓存线观测）"
    assert u.get("reasoning_tokens") == 30
    assert p._take_reasoning() == "先分析需求", "思维链摘要必须可被引擎取回"
    assert p._take_reasoning() == ""  # 取后清空（不跨轮串扰）


def test_responses_parses_deepseek_reasoning_text_content():
    """DeepSeek Responses 实测（2026-09-30）：reasoning 文本在
    content[].type=reasoning_text（summary 为空）——两种形状都要采集。"""
    class Http:
        def post(self, url, headers=None, json=None, timeout=None):
            return FakeResp({
                "output": [
                    {"type": "reasoning", "status": "completed",
                     "summary": [],
                     "content": [{"type": "reasoning_text",
                                  "text": "先读需求再写产物"}]},
                    {"type": "message", "content": [
                        {"type": "output_text", "text": "ok"}]},
                ],
                "usage": {"input_tokens": 10, "output_tokens": 5,
                          "output_tokens_details": {"reasoning_tokens": 7}},
            })

    p = OpenAIResponsesProvider(api_key="k", _http=Http())
    p.chat([{"role": "user", "content": "x"}])
    assert p._take_reasoning() == "先读需求再写产物"


def test_prompt_cache_key_injected_from_instance():
    """Pi 同款：OpenAI 兼容请求注入 prompt_cache_key（会话亲和——修复死方法）。
    键来源：provider 实例 _cache_key（引擎设置——会话/工作区标识）；无则省略。"""
    from wuxing.llm.openai import OpenAIChatProvider

    captured = {}

    class FakeResp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 1}}

    class FakeHttp:
        def post(self, url, headers=None, json=None, timeout=None):
            captured["payload"] = json
            return FakeResp()

    p = OpenAIChatProvider(model="m", api_key="k", _http=FakeHttp())
    p._cache_key = "sess-abc-123"
    out = p.chat([{"role": "user", "content": "hi"}])
    assert out == "ok"
    assert captured["payload"].get("prompt_cache_key") == "sess-abc-123", \
        f"必须注入会话键（Pi 同款）：{captured['payload']}"
    # 键裁剪：>64 字符截断（Pi clampOpenAIPromptCacheKey 同款）
    p._cache_key = "x" * 100
    p.chat([{"role": "user", "content": "hi"}])
    assert len(captured["payload"]["prompt_cache_key"]) == 64, \
        "会话键必须裁剪到 64 字符（OpenAI 限制）"
    # 无键 → 不注入
    p._cache_key = ""
    p.chat([{"role": "user", "content": "hi"}])
    assert "prompt_cache_key" not in captured["payload"]


def test_usage_parses_official_cache_fields():
    """DeepSeek 官方口径：usage 必须解析 prompt_cache_hit_tokens **和**
    prompt_cache_miss_tokens 双字段（不再用减法隐含 miss——直接问询 API）。"""
    from wuxing.llm.openai import OpenAIChatProvider

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}],
                    "usage": {"prompt_tokens": 1000, "completion_tokens": 10,
                              "prompt_cache_hit_tokens": 800,
                              "prompt_cache_miss_tokens": 200}}

    class FakeHttp:
        def post(self, url, headers=None, json=None, timeout=None):
            return FakeResp()

    p = OpenAIChatProvider(model="m", api_key="k", _http=FakeHttp())
    p.chat([{"role": "user", "content": "hi"}])
    u = p.usage_history[-1]
    assert u["cache_read"] == 800, "命中字段直接来自 API（prompt_cache_hit_tokens）"
    assert u.get("cache_miss") == 200, \
        "未命中字段必须直接来自 API（prompt_cache_miss_tokens）"


def test_openai_explicit_temperature_honored():
    """B 级修复：spec 显式 temperature（如 0.7）首轮必须生效——
    此前被重试温度序列覆盖（配置失效；kimi 场景 None 仍省略）。"""
    seen = {}

    class Http:
        def post(self, url, **kw):
            seen["json"] = kw["json"]
            return FakeResp({"choices": [{"message": {"content": "ok"}}]})

    p = OpenAIChatProvider(api_key="k", _http=Http(), temperature=0.7)
    p.chat([{"role": "user", "content": "x"}])
    assert seen["json"]["temperature"] == 0.7, \
        "显式 temperature 必须生效（不得被重试温度序列覆盖）"


def test_openai_reasoning_content_captured():
    """思维链观测（2026-09-11 用户要求）：DeepSeek-flash 的 reasoning_content
    必须可被 _take_reasoning 取回（当次调用；取后清空——不跨轮串扰）。"""
    class Http:
        def post(self, url, **kw):
            return FakeResp({"choices": [{"message": {
                "role": "assistant", "content": "ok",
                "reasoning_content": "分析：先确认需求再写产物"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5,
                          "completion_tokens_details": {"reasoning_tokens": 30}}})

    p = OpenAIChatProvider(api_key="k", _http=Http())
    p.chat([{"role": "user", "content": "x"}])
    assert p._take_reasoning() == "分析：先确认需求再写产物"
    assert p._take_reasoning() == ""  # 取后清空
    assert p.usage_history[-1].get("reasoning_tokens") == 30


# ── 思维链流式专项 Task 1（2026-10-01）：chat_stream（Responses SSE） ──


def _sse(obj):
    import json as _json
    return "data: " + _json.dumps(obj, ensure_ascii=False)


class FakeStreamResp:
    """SSE 响应假体（iter_lines 与 requests.Response 同形）。"""

    def __init__(self, lines):
        self._lines = lines

    def raise_for_status(self):
        pass

    def iter_lines(self):
        yield from self._lines


def test_responses_chat_stream_parses_sse_deltas():
    """Task 1-1：chat_stream 解析 SSE 增量事件。

    - response.reasoning_text.delta → on_delta("reasoning", …) 得增量序列
    - response.output_text.delta → on_delta("text", …)；文本与 chat() 同构
    - function_call_arguments.delta + output_item.done → 工具调用同 chat()
    - response.completed → usage 落账；[DONE] 终止（其后事件不再读）
    - 成功路径 last_stream_error 为空；_take_reasoning 取回整段思维链
    """
    event_lines = [
        "event: response.reasoning_text.delta",
        _sse({"type": "response.reasoning_text.delta", "delta": "先分析"}),
        _sse({"type": "response.reasoning_text.delta", "delta": "需求"}),
        _sse({"type": "response.output_text.delta", "item_id": "msg1",
              "delta": "我"}),
        _sse({"type": "response.output_text.delta", "item_id": "msg1",
              "delta": "来写文件"}),
        _sse({"type": "response.function_call_arguments.delta",
              "item_id": "fc1", "delta": '{"path": '}),
        _sse({"type": "response.function_call_arguments.delta",
              "item_id": "fc1", "delta": '"a.txt"}'}),
        _sse({"type": "response.output_item.done", "item": {
            "type": "function_call", "id": "fc1", "call_id": "c1",
            "name": "write_file", "arguments": '{"path": "a.txt"}'}}),
        _sse({"type": "response.completed", "response": {
            "output": [], "usage": {
                "input_tokens": 1000, "output_tokens": 50,
                "input_tokens_details": {"cached_tokens": 800},
                "output_tokens_details": {"reasoning_tokens": 30}}}}),
        "data: [DONE]",
        _sse({"type": "response.output_text.delta", "item_id": "msg1",
              "delta": "收到 DONE 后不得再读"}),
    ]
    captured = {}

    class Http:
        def post(self, url, headers=None, json=None, timeout=None, stream=None):
            captured["payload"] = json
            captured["stream"] = stream
            return FakeStreamResp(event_lines)

    p = OpenAIResponsesProvider(api_key="k", _http=Http())
    deltas = []
    tools = [{"type": "function", "function": {
        "name": "write_file", "description": "写文件",
        "parameters": {"type": "object", "properties": {}}}}]
    out = p.chat_stream([{"role": "user", "content": "x"}], tools=tools,
                        on_delta=lambda k, t: deltas.append((k, t)))
    from wuxing.llm.tool_results import ToolCallResult
    assert isinstance(out, ToolCallResult)
    assert out.text == "我来写文件"
    assert out.tool_calls == [{"name": "write_file",
                               "arguments": {"path": "a.txt"}}]
    assert deltas == [("reasoning", "先分析"), ("reasoning", "需求"),
                      ("text", "我"), ("text", "来写文件")]
    assert p.last_stream_error == ""
    assert p._take_reasoning() == "先分析需求"
    assert p._take_reasoning() == ""  # 取后清空（不跨轮串扰）
    u = p.usage_history[-1]
    assert u["input"] == 1000 and u["cache_read"] == 800
    assert u.get("reasoning_tokens") == 30
    # 请求面：stream=True + 工具扁平格式（与 chat() 同款）
    assert captured["stream"] is True
    assert captured["payload"]["stream"] is True
    assert captured["payload"]["tools"] == [
        {"type": "function", "name": "write_file", "description": "写文件",
         "parameters": {"type": "object", "properties": {}}}]


def test_responses_chat_stream_partial_on_disconnect():
    """Task 1-2：流中途断连 → 已收内容按现状返回 + 错误可见（不静默）。"""
    import requests as _requests

    class BoomResp:
        def raise_for_status(self):
            pass

        def iter_lines(self):
            yield _sse({"type": "response.reasoning_text.delta",
                        "delta": "思考"})
            yield _sse({"type": "response.output_text.delta", "item_id": "m1",
                        "delta": "部分"})
            raise _requests.ConnectionError("connection reset by peer")

    class Http:
        def post(self, url, **kw):
            return BoomResp()

    p = OpenAIResponsesProvider(api_key="k", _http=Http())
    out = p.chat_stream([{"role": "user", "content": "x"}])
    assert out == "部分"
    assert "ConnectionError" in p.last_stream_error
    assert "connection reset" in p.last_stream_error
    assert p._take_reasoning() == "思考"  # 已收思维链仍可取回


def test_responses_stream_unsupported_cached_after_400():
    """v43-⑤ 流式降噪：端点 400（不支持流式）→ 首次降级并缓存；后续不再发无效 stream 请求。"""
    import requests as _requests

    class Http:
        def __init__(self):
            self.stream_posts = 0

        def post(self, url, headers=None, json=None, timeout=None, stream=None):
            if json and json.get("stream"):
                self.stream_posts += 1
                resp = FakeResp({})
                resp.iter_lines = lambda: iter(())  # 具备流式接口（走到 raise_for_status）

                def _raise():
                    err = _requests.HTTPError("400 Client Error")
                    err.response = type("R", (), {"status_code": 400})()
                    raise err

                resp.raise_for_status = _raise
                return resp
            return FakeResp({"output": [{"type": "message", "content": [
                {"type": "output_text", "text": "chat-ok"}]}]})

    http = Http()
    p = OpenAIResponsesProvider(api_key="k", _http=http)
    assert p.supports_stream() is True
    assert p.chat_stream([{"role": "user", "content": "x"}]) == "chat-ok"
    assert http.stream_posts == 1
    assert p.supports_stream() is False
    assert p.last_stream_error
    assert p.chat_stream([{"role": "user", "content": "x"}]) == "chat-ok"
    assert http.stream_posts == 1, "缓存后不得再发无效 stream 请求（降噪）"


def test_responses_chat_stream_falls_back_when_response_not_streamable():
    """Task 1-2：响应无 iter_lines（不支持流式）→ 回退 chat()（原因可见）。"""
    class Http:
        def post(self, url, headers=None, json=None, timeout=None, stream=None):
            return FakeResp({"output": [
                {"type": "message", "content": [
                    {"type": "output_text", "text": "fallback-ok"}]}]})

    p = OpenAIResponsesProvider(api_key="k", _http=Http())
    out = p.chat_stream([{"role": "user", "content": "x"}])
    assert out == "fallback-ok"
    assert p.last_stream_error  # 回退原因可见（非静默）


def test_responses_chat_stream_falls_back_when_post_rejects_stream_kwarg():
    """Task 1-2：HTTP 假体/网关不接受 stream 参数（TypeError）→ 回退 chat()。"""
    calls = {"n": 0}

    class Http:
        def post(self, url, headers=None, json=None, timeout=None, stream=None):
            if stream:
                raise TypeError("post() got an unexpected keyword argument 'stream'")
            calls["n"] += 1
            return FakeResp({"output": [
                {"type": "message", "content": [
                    {"type": "output_text", "text": "no-stream-ok"}]}]})

    p = OpenAIResponsesProvider(api_key="k", _http=Http())
    out = p.chat_stream([{"role": "user", "content": "x"}])
    assert out == "no-stream-ok"
    assert calls["n"] == 1
