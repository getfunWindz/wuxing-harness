"""S1：provider 条目级超时覆盖（spec.timeout > 全局）。"""
import pytest

from wuxing.config_schema import validate_config
from wuxing.llm.factory import create_provider


def test_spec_timeout_overrides_global():
    p = create_provider({"type": "openai", "model": "m", "api_key": "k",
                         "timeout": 240}, timeout=180)
    assert p.timeout == 240


def test_global_timeout_when_spec_absent():
    p = create_provider({"type": "openai", "model": "m", "api_key": "k"},
                        timeout=180)
    assert p.timeout == 180


def test_invalid_spec_timeout_rejected():
    with pytest.raises(ValueError):
        create_provider({"type": "openai", "model": "m", "api_key": "k",
                         "timeout": -1}, timeout=180)
    with pytest.raises(ValueError):
        create_provider({"type": "openai", "model": "m", "api_key": "k",
                         "timeout": 0}, timeout=180)


def test_schema_validates_providers_timeout():
    ok = validate_config({"providers": {"p1": {"type": "openai",
                                               "timeout": 240}}})
    assert ok == []
    bad = validate_config({"providers": {"p1": {"type": "openai",
                                                "timeout": -5}}})
    assert any("providers.p1.timeout" in e for e in bad)
