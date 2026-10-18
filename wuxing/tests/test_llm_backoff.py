from wuxing.llm.base import BaseLlmProvider


def test_default_max_retries_four():
    """P12 韧性决策：默认重试 4 次（退避 1+2+4+8=15s——覆盖中转站中等防护窗口）。"""
    class P(BaseLlmProvider):
        def name(self): return "p"
        def chat(self, messages, tools=None):
            return self._retry_with_backoff(lambda: "ok")
    p = P()
    assert p.max_retries == 4

def test_backoff_covers_15s_window(monkeypatch):
    # 4 次重试 → 1+2+4+8 = 15s 总退避
    class Slow(BaseLlmProvider):
        def __init__(self):
            super().__init__(max_retries=4)
            self.calls = 0
        def name(self): return "s"
        def chat(self, messages, tools=None):
            return self._retry_with_backoff(self._once)
        def _once(self):
            self.calls += 1
            raise RuntimeError("jitter")
    p = Slow()
    from wuxing.llm import base
    delays = []
    # 测试污染修复（B 类）：monkeypatch 自动还原——严防 time.sleep 泄漏到其他测试
    monkeypatch.setattr(base.time, "sleep", lambda s: delays.append(s))
    try:
        p.chat([{"role": "user", "content": "x"}])
        assert False
    except RuntimeError:
        # 期望 RuntimeError：退避耗尽后精确抛出
        pass
    assert delays == [1.0, 2.0, 4.0, 8.0]  # 15s 总退避


class _HttpError(Exception):
    """测试用 HTTP 异常（带 response.status_code——与 requests.HTTPError 同形）。"""

    def __init__(self, code: int):
        super().__init__(f"HTTP {code}")
        self.response = type("_Resp", (), {"status_code": code})()


def _http_err(code: int):
    return _HttpError(code)


def _retry_probe():
    from wuxing.llm.base import BaseLlmProvider

    class P(BaseLlmProvider):
        def __init__(self, exc):
            super().__init__(max_retries=4)
            self.calls = 0
            self._exc = exc

        def name(self):
            return "p"

        def chat(self, messages, tools=None):
            return self._retry_with_backoff(self._once)

        def _once(self):
            self.calls += 1
            raise self._exc

    return P


def test_backoff_skips_non_retryable_4xx(monkeypatch):
    """B2（技术债收口 2026-09-12）：401/403 等不可重试 4xx——不白耗 1+2+4+8s 退避。"""
    import pytest

    from wuxing.llm import base
    P = _retry_probe()
    p = P(_http_err(401))
    delays = []
    monkeypatch.setattr(base.time, "sleep", lambda s: delays.append(s))
    with pytest.raises(_HttpError):
        p.chat([{"role": "user", "content": "x"}])
    assert p.calls == 1 and delays == [], \
        f"401 不得重试（calls={p.calls}, delays={delays}）"


def test_backoff_retries_429_and_5xx(monkeypatch):
    """429（限流）与 5xx（服务端）仍按指数退避重试。"""
    import pytest

    from wuxing.llm import base
    for code in (429, 500):
        P = _retry_probe()
        p = P(_http_err(code))
        delays = []

        def _sleep(s, _d=delays):
            _d.append(s)

        monkeypatch.setattr(base.time, "sleep", _sleep)
        with pytest.raises(_HttpError):
            p.chat([{"role": "user", "content": "x"}])
        assert p.calls == 5 and delays == [1.0, 2.0, 4.0, 8.0], \
            f"{code} 应重试 4 次（calls={p.calls}, delays={delays}）"
