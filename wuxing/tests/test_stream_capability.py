"""v43-⑤：流式能力检查——引擎不向不支持流式的 provider 发起 stream 尝试。

背景（v43 立项登记）：deepseek `/responses` 不支持流式——每次真实调用先发一次
必然 400 的 stream 请求再回退 `chat`（无效请求 + 日志噪声）。纪律：能力缓存后
引擎直接走 `chat`（零无效请求、零重复告警）。
"""
import pathlib

from wuxing.config import EngineConfig
from wuxing.runner import Runner
from wuxing.workspace import Workspace


class _CapLlm:
    def __init__(self, supported):
        self._supported = supported
        self.stream_calls = 0
        self.chat_calls = 0

    def name(self):
        return "cap"

    def supports_stream(self):
        return self._supported

    def chat_stream(self, messages, tools=None, on_delta=None):
        self.stream_calls += 1
        return "stream"

    def chat(self, messages, tools=None):
        self.chat_calls += 1
        return "chat"


def _runner(tmp_path, llm):
    ws = Workspace(pathlib.Path(tmp_path))
    r = Runner(EngineConfig(), None, ws, llm, [])
    r._messages = [{"role": "user", "content": "x"}]
    r._tool_schemas = []
    return r


def test_stream_skipped_when_capability_false(tmp_path):
    llm = _CapLlm(supported=False)
    r = _runner(tmp_path, llm)
    out = r._chat_once(llm, on_delta=lambda kind, text: None)
    assert out == "chat"
    assert llm.stream_calls == 0, "能力为假时不得发起 stream 尝试"
    assert llm.chat_calls == 1


def test_stream_used_when_capability_true(tmp_path):
    llm = _CapLlm(supported=True)
    r = _runner(tmp_path, llm)
    out = r._chat_once(llm, on_delta=lambda kind, text: None)
    assert out == "stream" and llm.stream_calls == 1


def test_no_capability_method_defaults_to_attempt(tmp_path):
    """无 supports_stream 的 provider → 维持既有尝试行为（兼容）。"""

    class _NoCap:
        def __init__(self):
            self.stream_calls = 0
            self.chat_calls = 0

        def name(self):
            return "plain"

        def chat_stream(self, messages, tools=None, on_delta=None):
            self.stream_calls += 1
            return "stream"

        def chat(self, messages, tools=None):
            self.chat_calls += 1
            return "chat"

    llm = _NoCap()
    r = _runner(tmp_path, llm)
    out = r._chat_once(llm, on_delta=lambda kind, text: None)
    assert out == "stream" and llm.stream_calls == 1
