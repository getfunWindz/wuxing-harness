"""TDD（双模式批 1 · Task 1）：配置双写——全局默认放宽 + 模式新键。

依据：docs/plans/2026-09-23-wuxing-dual-mode-batch1.md Task 1 + 设计 §4.4/§7。
纪律：config.py（EngineConfig）与 config_schema.py（FIELD_SPECS）双写一致。
"""
from wuxing.config import EngineConfig
from wuxing.config_schema import FIELD_SPECS, validate_config


def test_dual_mode_config_defaults():
    cfg = EngineConfig()
    assert cfg.conversation_max_chars == 10000
    assert cfg.fsc_digest_max_chars == 7000
    assert cfg.mode_default == "minimal-standard"
    assert cfg.mode_picker_enabled is True
    assert cfg.minimal_pure_tools == ("bash", "read_file", "write_file",
                                      "write_artifact", "read_dependency")
    assert cfg.minimal_pure_auto_confirm is True
    spec = {s.name: s for s in FIELD_SPECS}
    for key in ("conversation_max_chars", "fsc_digest_max_chars", "mode_default",
                "mode_picker_enabled", "minimal_pure_tools",
                "minimal_pure_auto_confirm"):
        assert key in spec, key


def test_dual_mode_defaults_schema_matches_engine_config():
    """双写纪律：FIELD_SPECS 默认值必须与 EngineConfig 一致。"""
    spec = {s.name: s for s in FIELD_SPECS}
    cfg = EngineConfig()
    for key in ("conversation_max_chars", "fsc_digest_max_chars", "mode_default",
                "mode_picker_enabled", "minimal_pure_tools",
                "minimal_pure_auto_confirm"):
        assert spec[key].default == getattr(cfg, key), key


def test_mode_default_enum_validated():
    """模式 id 合法集：minimal-pure / minimal-standard / theroad（wayfinder 旧值兼容读）。"""
    assert validate_config({"mode_default": "minimal-standard"}) == []
    assert validate_config({"mode_default": "minimal-pure"}) == []
    assert validate_config({"mode_default": "theroad"}) == []
    assert validate_config({"mode_default": "wayfinder"}) == []  # 批 1 更名兼容
    assert len(validate_config({"mode_default": "bogus"})) >= 1


def test_context_band_config_defaults_and_validation():
    """双模式批 2：黄金期阈值双写 + 交叉校验（0 < golden < managed ≤ 1）。"""
    from wuxing.config import EngineConfig
    from wuxing.config_schema import FIELD_SPECS, validate_config
    cfg = EngineConfig()
    assert cfg.context_golden_pct == 0.2
    assert cfg.context_managed_pct == 0.5
    names = {s.name for s in FIELD_SPECS}
    assert {"context_golden_pct", "context_managed_pct"} <= names
    # 合法组合
    assert validate_config({"context_golden_pct": 0.3,
                            "context_managed_pct": 0.6}) == []
    # 非法组合（早报）
    assert len(validate_config({"context_golden_pct": 0.8,
                                "context_managed_pct": 0.5})) >= 1
    assert len(validate_config({"context_golden_pct": 0.0,
                                "context_managed_pct": 0.5})) >= 1
    assert len(validate_config({"context_golden_pct": 0.2,
                                "context_managed_pct": 1.2})) >= 1
    assert len(validate_config({"context_golden_pct": 0.5,
                                "context_managed_pct": 0.5})) >= 1


def test_shell_remote_config_fields():
    """O5 安全门（T2）：shell_allow_hosts / shell_allow_origins 双写 + 默认空。"""
    from wuxing.config import EngineConfig
    from wuxing.config_schema import FIELD_SPECS, validate_config
    cfg = EngineConfig()
    assert cfg.shell_allow_hosts == []
    assert cfg.shell_allow_origins == []
    spec = {s.name: s for s in FIELD_SPECS}
    for key in ("shell_allow_hosts", "shell_allow_origins"):
        assert key in spec, key
        assert spec[key].default == getattr(cfg, key), key
    assert validate_config({"shell_allow_hosts": ["wuxing.example.com"]}) == []
    assert validate_config(
        {"shell_allow_origins": ["https://wuxing.example.com"]}) == []
    assert validate_config({"shell_allow_hosts": "nope"}) != []
