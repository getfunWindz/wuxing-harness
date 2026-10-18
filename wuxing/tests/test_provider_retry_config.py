"""S1：自动恢复配置双写与校验。"""
from wuxing.config import EngineConfig
from wuxing.config_schema import FIELD_SPECS, validate_config


def test_defaults():
    cfg = EngineConfig()
    assert cfg.provider_retry_max == 1
    assert cfg.provider_retry_backoff_s == 15.0


def test_schema_double_write():
    names = {f.name for f in FIELD_SPECS}
    assert {"provider_retry_max", "provider_retry_backoff_s"} <= names


def test_validation_rejects_negative():
    assert any("provider_retry_max" in e and "≥ 0" in e
               for e in validate_config({"provider_retry_max": -1}))
    assert any("provider_retry_backoff_s" in e and "≥ 0" in e
               for e in validate_config({"provider_retry_backoff_s": -0.5}))


def test_validation_accepts_zero_and_positive():
    assert validate_config({"provider_retry_max": 0,
                            "provider_retry_backoff_s": 0}) == []
    assert validate_config({"provider_retry_max": 2,
                            "provider_retry_backoff_s": 30.0}) == []
