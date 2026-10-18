from wuxing.config import EngineConfig
from wuxing.registry import DomainRegistry


def test_default_active_excludes_conditional():
    reg = DomainRegistry(EngineConfig())
    assert reg.active_ids() == ["plan", "execute", "verify"]  # user 默认未启用

def test_activate_user_then_available():
    reg = DomainRegistry(EngineConfig())
    reg.activate(["user"])
    assert "user" in reg.active_ids()
    d = reg.get("user")
    assert d.domain_id == "user"

def test_get_inactive_conditional_raises():
    reg = DomainRegistry(EngineConfig())
    try:
        reg.get("user")
        assert False
    except KeyError:
        # 期望 KeyError（不抛则上方 assert False 先失败）
        pass

def test_get_always_domains_never_raises():
    reg = DomainRegistry(EngineConfig())
    assert reg.get("plan").domain_id == "plan"
    assert reg.get("execute").domain_id == "execute"
    assert reg.get("verify").domain_id == "verify"

def test_activate_unknown_raises():
    reg = DomainRegistry(EngineConfig())
    try:
        reg.activate(["nope"])
        assert False
    except KeyError:
        # 期望 KeyError（不抛则上方 assert False 先失败）
        pass
