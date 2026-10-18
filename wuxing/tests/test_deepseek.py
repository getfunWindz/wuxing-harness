from wuxing.llm.deepseek import DeepSeekLlmProvider


class FakeResponse:
    def __init__(self, content):
        self._content = content
    def raise_for_status(self): pass
    def json(self): return {"choices": [{"message": {"content": self._content}}]}

class FakeRequests:
    def __init__(self, content):
        self.content = content
        self.calls = 0
    def post(self, url, **kw):
        self.calls += 1
        return FakeResponse(self.content)

def test_deepseek_chat_returns_content():
    llm = DeepSeekLlmProvider(api_key="test-key", _http=FakeRequests("hi"))
    out = llm.chat([{"role": "user", "content": "hello"}])
    assert out == "hi"
    assert llm.call_count == 1

def test_deepseek_retries_on_network_error():
    class FlakyRequests:
        def __init__(self): self.calls = 0
        def post(self, url, **kw):
            self.calls += 1
            if self.calls == 1:
                import requests
                raise requests.ConnectionError("boom")
            return FakeResponse("ok")
    llm = DeepSeekLlmProvider(api_key="k", _http=FlakyRequests(), max_retries=2)
    assert llm.chat([{"role": "user", "content": "x"}]) == "ok"
    assert llm.call_count == 2

def test_deepseek_missing_key_raises():
    import os
    os.environ.pop("DEEPSEEK_API_KEY", None)
    os.environ.pop("OPENAI_API_KEY", None)
    # 延迟校验：构造不抛错，chat() 时抛 RuntimeError（明确失败而非静默）
    p = DeepSeekLlmProvider(api_key="")
    try:
        p.chat([{"role": "user", "content": "x"}])
        assert False
    except RuntimeError:
        # 期望 RuntimeError（未配置凭据）：不抛则上行 assert False 失败
        pass
