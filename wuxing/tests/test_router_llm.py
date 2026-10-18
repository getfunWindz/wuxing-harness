from wuxing.llm.router import ModelRouter


def test_router_domain_specific():
    r = ModelRouter({
        "plan": "deepseek:deepseek-chat",
        "verify": "anthropic:claude-sonnet-4-5",
        "_default": "mock",
    })
    assert r.for_domain("plan").name().startswith("deepseek")
    assert r.for_domain("verify").name().startswith("anthropic")
    assert r.for_domain("execute").name() == "MockLlmProvider"  # 未指定 → 默认

def test_router_fallback_default():
    r = ModelRouter({"plan": "mock"})
    assert r.for_domain("execute").name() == "MockLlmProvider"  # 无默认 → mock
