from wuxing.llm.anthropic import AnthropicProvider
from wuxing.llm.deepseek import DeepSeekLlmProvider
from wuxing.llm.openai import OpenAIChatProvider


def test_anthropic_injects_cache_control_on_system():
    p = AnthropicProvider(api_key="k")
    msgs = p.build_messages_prefix(["稳定系统段"], tools=None)
    assert p.cache_capabilities()["server_prompt_cache"] == "anthropic"
    # system 段带 cache_control 标记（Anthropic 格式：ephemeral）
    assert "cache_control" in str(msgs) and "ephemeral" in str(msgs)

def test_anthropic_no_marker_without_capability():
    # 若能力为 none 则不注入（防御：非 anthropic 路径不污染）
    p = AnthropicProvider(api_key="k")
    p.build_messages_prefix(["段"], tools=None)
    assert p.cache_capabilities()["server_prompt_cache"] == "anthropic"  # 能力存在
    # 手动模拟能力关闭场景（协议兼容性防御）
    p.cache_capabilities = lambda: {"server_prompt_cache": "none"}
    msgs2 = p.build_messages_prefix(["段"], tools=None)
    assert "cache_control" not in str(msgs2)

def test_openai_adds_prompt_cache_key():
    p = OpenAIChatProvider(api_key="k")
    payload = p.build_payload(["稳定段", "变体尾"], tools=None)
    assert "prompt_cache_key" in payload  # OpenAI 兼容前缀缓存键

def test_deepseek_no_injection():
    p = DeepSeekLlmProvider(api_key="k")
    payload = p.build_payload(["稳定段"], tools=None)
    assert "cache_control" not in str(payload)
    assert "prompt_cache_key" not in str(payload)  # none 能力零注入
