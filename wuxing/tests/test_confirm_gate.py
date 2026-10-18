from wuxing.config import EngineConfig
from wuxing.confirm_gate import ConfirmGate


def test_gate_default_auto_confirm():
    cfg = EngineConfig()  # confirm_threshold=0.0
    gate = ConfirmGate(cfg)
    assert gate.needs_confirm("execute", "F-1") is False

def test_gate_threshold_all_confirm():
    cfg = EngineConfig(confirm_threshold=1.0)
    gate = ConfirmGate(cfg)
    assert gate.needs_confirm("plan", "F-1") is True

def test_gate_domain_specific_rules():
    cfg = EngineConfig(confirm_threshold=0.6)
    gate = ConfirmGate(cfg)
    # 域特殊规则：verify/user 永远确认（配置域清单）
    assert gate.needs_confirm("verify", "F-1") is True
    assert gate.needs_confirm("user", "F-1") is True
    assert gate.needs_confirm("execute", "F-1") is False

def test_gate_confirm_callback_flow():
    cfg = EngineConfig(confirm_threshold=1.0)
    gate = ConfirmGate(cfg)
    called = []
    gate.on_confirm(lambda unit_id, approve, reason: called.append((unit_id, approve, reason)))
    gate.notify("F-1", approve=True, reason="")
    assert called == [("F-1", True, "")]
