from wuxing.config import EngineConfig
from wuxing.registry import DomainRegistry


def test_default_4_domains():
    reg = DomainRegistry(EngineConfig())
    assert set(reg.all_domain_ids()) == {"plan", "execute", "verify", "user"}

def test_get_domain():
    reg = DomainRegistry(EngineConfig())
    d = reg.get("execute")
    assert d.title == "执行域"
    assert "write_artifact" in d.tool_whitelist

def test_unknown_domain_raises():
    reg = DomainRegistry(EngineConfig())
    try:
        reg.get("nope")
        assert False, "should raise"
    except KeyError:
        # 期望 KeyError（不抛则上方 assert False 先失败）
        pass

def test_domain_contract_valid():
    reg = DomainRegistry(EngineConfig())
    for did in reg.all_domain_ids():
        # 条件域启用后也能校验（P8.1：契约完整性对全部域生效）
        if reg.is_conditional(did):
            reg.activate([did])
        d = reg.get(did)
        assert d.input_schema and d.output_schema
