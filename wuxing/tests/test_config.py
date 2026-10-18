from wuxing.config import EngineConfig


def test_default_guards():
    cfg = EngineConfig()
    assert cfg.max_loop_rounds == 6
    assert cfg.max_unit_budget == 5  # L4 真跑调参：3 轮不足（探索+产出+声明）
    assert cfg.default_artifact_dir == "artifacts"

def test_use_real_shape_default_on():
    """用户裁决 2026-09-18：真实形状化默认开启（可在设置自主关闭）。"""
    from wuxing.config_schema import FIELD_SPECS
    assert EngineConfig().use_real_shape is True
    spec = next(s for s in FIELD_SPECS if s.name == "use_real_shape")
    assert spec.default is True


def test_config_override():
    cfg = EngineConfig(max_loop_rounds=10)
    assert cfg.max_loop_rounds == 10
    assert cfg.max_unit_budget == 5  # 未覆盖字段保持默认（L4 调参）
