"""DeepSeek RealLLM 测试（协议层：key 读取 / JSON 解析 / 重试；测试不触网）。"""
import pytest

from golden_ratio.realllm import DeepSeekLLM


class FakeHTTP(DeepSeekLLM):
    """覆盖 _chat 的测试双：固定返回内容，记录调用与温度。"""

    def __init__(self, result, **kw):
        super().__init__(api_key="test-key", **kw)
        self._result = result
        self.chat_calls = 0
        self.temperatures = []

    def _chat(self, messages, json_mode=True, temperature=0.0):
        self.chat_calls += 1
        self.temperatures.append(temperature)
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def test_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        DeepSeekLLM(api_key="")


def test_api_key_from_env(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env-key")
    llm = DeepSeekLLM()
    assert llm.api_key == "sk-env-key"


def test_shape_task_parses_json_response():
    llm = FakeHTTP({
        "nodes": [{"id": "n1", "text": "撰写请假邮件", "domain_dist": {"写作": 0.9},
                   "trades": ["创作"], "complexity": "low",
                   "deliverable": "text", "color_weight": 0.5}],
        "edges": [],
        "total_size": 1.0,
    })
    out = llm.shape_task("写一封请假邮件")
    assert out["nodes"][0]["id"] == "n1"
    assert llm.chat_calls == 1


def test_shape_task_raises_on_invalid_json():
    llm = FakeHTTP("这不是JSON{{{")
    with pytest.raises(ValueError):
        llm.shape_task("写一封请假邮件")


def test_merge_nodes_calls_chat_and_parses_groups():
    llm = FakeHTTP([["n1", "n2"], ["n3"]])
    groups = llm.merge_nodes([{"id": "n1"}, {"id": "n2"}, {"id": "n3"}])
    assert groups == [["n1", "n2"], ["n3"]]
    assert llm.chat_calls == 1


def test_rebalance_suggest_parses_moves():
    llm = FakeHTTP({"moves": [{"from": "X", "to": "Y", "node_ids": ["n1"]}]})
    out = llm.rebalance_suggest({"fragments": []})
    assert out["moves"][0]["from"] == "X"


def test_score_keys_parses_scores():
    llm = FakeHTTP({"开发": 0.9, "用户": 0.7})
    out = llm.score_keys(["开发", "用户"])
    assert out == {"开发": 0.9, "用户": 0.7}


def test_retries_then_raises_on_api_error():
    llm = FakeHTTP(OSError("connection refused"))      # 连接类异常 → 重试
    with pytest.raises(OSError):
        llm.shape_task("x")
    assert llm.chat_calls == llm.max_retries + 1, "应重试 max_retries 次后放弃"


def test_success_after_retry():
    """第一次失败第二次成功 → 返回解析结果。"""
    class Flaky(FakeHTTP):
        def _chat(self, messages, json_mode=True, temperature=0.0):
            self.chat_calls += 1
            self.temperatures.append(temperature)
            if self.chat_calls == 1:
                raise OSError("timeout")
            return {"nodes": [], "edges": [], "total_size": 1.0}

    llm = Flaky({})
    out = llm.shape_task("x")
    assert llm.chat_calls == 2
    assert out["total_size"] == 1.0


def test_retry_escalates_temperature():
    """重试应提高 temperature（0→0.3→0.6）——纠错重试需要输出多样性。"""
    llm = FakeHTTP(OSError("boom"))
    with pytest.raises(OSError):
        llm.shape_task("x")
    assert llm.temperatures == [0.0, 0.3, 0.6], "温度应按 0→0.3→0.6 递增"
