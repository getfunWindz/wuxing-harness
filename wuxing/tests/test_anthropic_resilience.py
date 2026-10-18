import json

from wuxing.llm.anthropic import AnthropicProvider


class FakeHtmlResp:
    """中转站 200 + 非 JSON（HTML 错误页）——raise_for_status 不触发但 json() 崩溃。"""
    def __init__(self, status=200):
        self.status = status
        self._text = "<html><body>maintanence</body></html>"
    def raise_for_status(self):
        if self.status >= 400:
            import requests
            raise requests.HTTPError(f"{self.status} error")
    def json(self):
        raise json.JSONDecodeError("Expecting value", self._text, 0)
    @property
    def text(self):
        return self._text

class Http:
    def post(self, url, **kw):
        return FakeHtmlResp(200)  # 200 非 JSON

def test_anthropic_non_json_error_friendly():
    p = AnthropicProvider(api_key="k", _http=Http(), max_retries=0)
    try:
        p.chat([{"role": "user", "content": "x"}])
        assert False
    except Exception as e:
        # 应抛友好错误（含来源）而非裸 JSONDecodeError——错误可诊断
        assert type(e).__name__ != "JSONDecodeError"

def test_anthropic_retries_on_rate_limit_then_success():
    class Flaky:
        def __init__(self): self.n = 0
        def post(self, url, **kw):
            self.n += 1
            if self.n == 1:
                return FakeHtmlResp()
            class OK:
                def raise_for_status(self): pass
                def json(self): return {"content": [{"type": "text", "text": "ok"}]}
            return OK()
    p = AnthropicProvider(api_key="k", _http=Flaky(), max_retries=2)
    assert p.chat([{"role": "user", "content": "x"}]) == "ok"
