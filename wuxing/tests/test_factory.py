from wuxing.llm.factory import create_provider


def test_factory_mock():
    p = create_provider("mock")
    assert p.name() == "MockLlmProvider"

def test_factory_deepseek_string():
    p = create_provider("deepseek:deepseek-chat")
    assert p.name().startswith("deepseek")

def test_factory_openai_compat_string():
    p = create_provider("openai:gpt-4o")
    assert p.name() == "openai-compat:gpt-4o"

def test_factory_anthropic_string():
    p = create_provider("anthropic:claude-sonnet-4-5")
    assert "anthropic" in p.name()

def test_factory_dict_full():
    p = create_provider({"type": "openai", "model": "qwen2.5",
                         "base_url": "https://my.vllm/v1"})
    assert p.name() == "openai-compat:qwen2.5"
    assert p.base_url == "https://my.vllm/v1"

def test_factory_unknown_raises():
    try:
        create_provider("hugo:gpt")
        assert False
    except ValueError:
        # 期望 ValueError（未知 provider）：不抛则上行 assert False 失败
        pass


def test_factory_heals_ref_via_registry(tmp_path, monkeypatch):
    """2026-10-01 修复 C：dict spec 缺凭据引用时，按 type+base_url 从 providers
    注册表回填 credential_ref（治旧数据；不改变显式提供 ref 的行为）。"""
    import wuxing.credentials as creds
    monkeypatch.setattr(creds, "credentials_path", lambda: tmp_path / "c.json")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    creds.set("DEEPSEEK_API_KEY", "sk-heal")
    providers = {"deepseek": {"type": "responses", "display_name": "DeepSeek",
                              "models": [{"id": "deepseek-flash"}],
                              "base_url": "https://api.deepseek.com/",
                              "credential_ref": "DEEPSEEK_API_KEY"}}
    p = create_provider({"type": "responses", "model": "deepseek-flash",
                         "base_url": "https://api.deepseek.com"},
                        providers=providers)
    assert p.api_key == "sk-heal"


def test_factory_explicit_key_not_overridden_by_registry(tmp_path, monkeypatch):
    import wuxing.credentials as creds
    monkeypatch.setattr(creds, "credentials_path", lambda: tmp_path / "c.json")
    creds.set("DEEPSEEK_API_KEY", "sk-store")
    providers = {"deepseek": {"type": "responses",
                              "base_url": "https://api.deepseek.com/",
                              "credential_ref": "DEEPSEEK_API_KEY"}}
    p = create_provider({"type": "responses", "model": "m",
                         "base_url": "https://api.deepseek.com",
                         "api_key": "sk-explicit"}, providers=providers)
    assert p.api_key == "sk-explicit"


def test_factory_zhipu_openai_compat():
    """智谱 GLM：OpenAI 兼容 spec（base_url+api_key_env——零新 provider 代码）。"""
    import os
    os.environ["ZHIPU_API_KEY"] = "test-zhipu-key"
    from wuxing.llm.factory import create_provider
    p = create_provider({"type": "openai", "model": "glm-5.3-flash",
                         "base_url": "https://open.bigmodel.cn/api/paas/v4",
                         "api_key_env": "ZHIPU_API_KEY"})
    assert p.base_url == "https://open.bigmodel.cn/api/paas/v4"
    assert p.api_key == "test-zhipu-key"
    assert p.model == "glm-5.3-flash"
    assert p.name().startswith("openai-compat")


def test_spec_credential_store_fallback(tmp_path, monkeypatch):
    """env 未设 → 凭据存储兜底；env 设置时优先于存储（R3-1/D2）。"""
    import wuxing.credentials as creds
    monkeypatch.setattr(creds, "credentials_path", lambda: tmp_path / "c.json")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    creds.set("DEEPSEEK_API_KEY", "sk-store")
    p = create_provider({"type": "deepseek", "model": "deepseek-chat"})
    assert p.api_key == "sk-store"
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env")
    p2 = create_provider({"type": "deepseek", "model": "deepseek-chat"})
    assert p2.api_key == "sk-env"


def test_spec_empty_credential_ref_skips_store(tmp_path, monkeypatch):
    """credential_ref='' → 不查存储（保留供应商原生认证链）。"""
    import wuxing.credentials as creds
    monkeypatch.setattr(creds, "credentials_path", lambda: tmp_path / "c.json")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    creds.set("ANTHROPIC_API_KEY", "sk-store")
    p = create_provider({"type": "anthropic", "model": "claude-x",
                         "credential_ref": ""})
    assert not p.api_key


def test_spec_explicit_api_key_env_wins_derived(tmp_path, monkeypatch):
    """显式 api_key_env 优先于派生 ref（自定义通道不与类型默认键串扰）。"""
    import wuxing.credentials as creds
    monkeypatch.setattr(creds, "credentials_path", lambda: tmp_path / "c.json")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("MICU_CLAUDE_KEY", raising=False)
    creds.set("MICU_CLAUDE_KEY", "sk-custom")
    p = create_provider({"type": "anthropic", "model": "claude-x",
                         "api_key_env": "MICU_CLAUDE_KEY"})
    assert p.api_key == "sk-custom"
