from wuxing.config import EngineConfig
from wuxing.confirm_gate import ConfirmGate


def test_mid_threshold_low_difficulty_auto():
    cfg = EngineConfig(confirm_threshold=0.5, confirm_threshold_difficulty=0.3)
    gate = ConfirmGate(cfg)
    # 低难度（difficulty=1）→ 不确认
    assert gate.needs_confirm("execute", "F-1", difficulty=1) is False

def test_mid_threshold_high_difficulty_confirm():
    cfg = EngineConfig(confirm_threshold=0.5, confirm_threshold_difficulty=0.3)
    gate = ConfirmGate(cfg)
    # 高难度（difficulty=5）→ 确认
    assert gate.needs_confirm("execute", "F-1", difficulty=5) is True

def test_mid_verify_always_confirm():
    cfg = EngineConfig(confirm_threshold=0.5, confirm_threshold_difficulty=0.3)
    gate = ConfirmGate(cfg)
    assert gate.needs_confirm("verify", "F-1", difficulty=1) is True  # 域规则覆盖

def test_ends_unchanged():
    # 0 = 全自动，1 = 全确认（P5 语义不变）
    cfg0 = EngineConfig(confirm_threshold=0.0)
    assert ConfirmGate(cfg0).needs_confirm("execute", "F-1", difficulty=5) is False
    cfg1 = EngineConfig(confirm_threshold=1.0)
    assert ConfirmGate(cfg1).needs_confirm("execute", "F-1", difficulty=1) is True
