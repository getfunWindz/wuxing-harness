from wuxing.config import EngineConfig
from wuxing.confirm_gate import ConfirmGate
from wuxing.registry import DomainRegistry


def _mk(reg=None):
    cfg = EngineConfig(confirm_threshold=1.0)
    return ConfirmGate(cfg, registry=reg or DomainRegistry(cfg))

def test_gate_respects_active_domains():
    cfg = EngineConfig(confirm_threshold=1.0)
    reg = DomainRegistry(cfg)
    gate = ConfirmGate(cfg, registry=reg)
    # user 未启用（条件域）→ 不确认（排除）
    assert gate.needs_confirm("user", "F-1") is False
    # 启用后 → 正常确认（域规则覆盖）
    reg.activate(["user"])
    assert gate.needs_confirm("user", "F-1") is True

def test_gate_verify_always_confirm():
    cfg = EngineConfig(confirm_threshold=1.0)
    gate = ConfirmGate(cfg, registry=DomainRegistry(cfg))
    assert gate.needs_confirm("verify", "F-1") is True
