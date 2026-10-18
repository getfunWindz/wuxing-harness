"""TDD · O2-2 P1：浏览器配置面（默认关 + 双表）。

设计：docs/WUXING_内置浏览器体验断言_设计_2026-10-07.md §3.1。
"""
from wuxing.config import EngineConfig
from wuxing.config_schema import FIELD_SPECS


def test_browser_config_defaults():
    cfg = EngineConfig()
    assert cfg.browser_enabled is False
    assert cfg.browser_domains_allow == []
    assert cfg.browser_domains_deny == []


def test_browser_fields_in_schema():
    names = {f.name for f in FIELD_SPECS}
    assert {"browser_enabled", "browser_domains_allow",
            "browser_domains_deny"} <= names


def test_browser_evaluate_config_default_off():
    """P3：evaluate 显式档——默认关（双闸之一）。"""
    cfg = EngineConfig()
    assert cfg.browser_evaluate_enabled is False


def test_browser_evaluate_field_in_schema():
    names = {f.name for f in FIELD_SPECS}
    assert "browser_evaluate_enabled" in names


def test_browser_identity_mode_default_and_schema():
    """§11.5-①：身份档默认 memory + 字段入 schema（双写）。"""
    cfg = EngineConfig()
    assert cfg.browser_identity_mode == "memory"
    names = {f.name for f in FIELD_SPECS}
    assert "browser_identity_mode" in names
