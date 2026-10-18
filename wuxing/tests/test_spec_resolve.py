"""R5-1：provider/model 引用解析（E1/E2）——向后兼容零迁移。"""
import pytest

from wuxing.llm.factory import create_provider, resolve_spec

PROVIDERS = {"deepseek": {"type": "deepseek", "base_url": "https://api.deepseek.com"},
             "micu-claude": {"type": "anthropic", "base_url": "https://api.micuapi.ai/v1",
                             "credential_ref": "MICU_CLAUDE_API_KEY"}}


def test_provider_ref_string_expands():
    spec = resolve_spec("micu-claude/claude-sonnet-5", PROVIDERS)
    assert spec == {"type": "anthropic", "model": "claude-sonnet-5",
                    "base_url": "https://api.micuapi.ai/v1",
                    "credential_ref": "MICU_CLAUDE_API_KEY"}


def test_provider_ref_model_with_slash_kept():
    spec = resolve_spec("openrouter/anthropic/claude-4",
                        {"openrouter": {"type": "openai"}})
    assert spec["model"] == "anthropic/claude-4"
    assert spec["type"] == "openai"


def test_dict_provider_ref_and_overrides():
    spec = resolve_spec({"provider": "deepseek", "model": "deepseek-v4-pro",
                         "temperature": 0.2}, PROVIDERS)
    assert spec["type"] == "deepseek" and spec["model"] == "deepseek-v4-pro"
    assert spec["base_url"] == "https://api.deepseek.com"
    assert spec["temperature"] == 0.2


def test_provider_entry_meta_not_leaked_into_spec():
    spec = resolve_spec("demo/demo-model", {
        "demo": {"type": "openai", "base_url": "https://x/v1",
                 "display_name": "演示", "models": [{"id": "demo-model"}]}})
    assert "display_name" not in spec and "models" not in spec
    assert spec["model"] == "demo-model"


def test_legacy_specs_untouched():
    assert resolve_spec("mock", PROVIDERS) == "mock"
    assert resolve_spec("deepseek:deepseek-chat", PROVIDERS) == "deepseek:deepseek-chat"
    raw = {"type": "openai", "model": "gpt-4o"}
    assert resolve_spec(raw, PROVIDERS) == raw


def test_unknown_provider_errors():
    with pytest.raises(ValueError):
        resolve_spec({"provider": "nope", "model": "m"}, PROVIDERS)


def test_create_provider_accepts_provider_ref():
    p = create_provider("deepseek/deepseek-chat", providers=PROVIDERS)
    assert p.name().startswith("deepseek")


def test_create_provider_providers_none_is_legacy():
    p = create_provider("deepseek:deepseek-chat")
    assert p.name().startswith("deepseek")
