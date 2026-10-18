from wuxing.llm.anthropic import AnthropicProvider
from wuxing.llm.deepseek import DeepSeekLlmProvider
from wuxing.llm.mock import MockLlmProvider
from wuxing.llm.openai import OpenAIChatProvider


def test_anthropic_reports_anthropic_cache():
    p = AnthropicProvider(api_key="k")
    caps = p.cache_capabilities()
    assert caps["server_prompt_cache"] == "anthropic"

def test_openai_reports_openai_prefix():
    p = OpenAIChatProvider(api_key="k")
    caps = p.cache_capabilities()
    assert caps["server_prompt_cache"] == "openai-completions"

def test_deepseek_reports_none():
    p = DeepSeekLlmProvider(api_key="k")
    assert p.cache_capabilities()["server_prompt_cache"] == "none"

def test_mock_reports_none():
    p = MockLlmProvider()
    assert p.cache_capabilities()["server_prompt_cache"] == "none"
