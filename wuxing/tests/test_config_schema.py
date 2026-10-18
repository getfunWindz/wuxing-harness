from wuxing.config_schema import validate_config


def test_valid_config_passes():
    errors = validate_config({"max_loop_rounds": 5})
    assert errors == []

def test_wrong_type_detected():
    errors = validate_config({"max_loop_rounds": "five"})
    assert len(errors) == 1
    assert "max_loop_rounds" in errors[0]

def test_unknown_field_warning():
    errors = validate_config({"nope": 1})
    assert len(errors) == 1

def test_enum_validation():
    # llm 类型枚举（deepseek/openai/anthropic/responses/mock）
    errors = validate_config({"llm": "hugo:gpt"})
    assert len(errors) >= 1
    errors2 = validate_config({"llm": "deepseek:deepseek-chat"})
    assert errors2 == []

def test_non_llm_enum_strict_equality():
    """C5（E0-4/P3-5）：非 llm 枚举字段严格相等——`full-access:junk` 拒绝。"""
    assert validate_config({"permission_profile": "full-access:junk"}) != []
    assert validate_config({"permission_profile": "full-access"}) == []
    assert validate_config({"sandbox_mode": "native:junk"}) != []
    assert validate_config({"sandbox_mode": "native"}) == []


def test_router_enum_validation():
    # router 域值必须合法 provider 类型
    errors = validate_config({"router": {"plan": "hugo:gpt", "_default": "mock"}})
    assert len(errors) >= 1


def test_schema_ref_field_allowed():
    """$schema 是 JSON Schema 注释字段（IDE 补全引用）——必须白名单放行。
    （阶段 2 发现：config.example.jsonc 自带 $schema 却过不了 validate_config——硬伤）"""
    from wuxing.config_schema import validate_config
    assert validate_config({"$schema": "./config.schema.json"}) == []
    assert validate_config({"$schema": "./config.schema.json", "llm": "mock"}) == []

def test_default_tools_filtered_at_engine():
    """配置补遗：default_tools 全局工具白名单（pi defaultTools 参考）——引擎级过滤。"""
    import pathlib
    import tempfile

    from wuxing.config import EngineConfig
    from wuxing.engine import Engine
    cfg = EngineConfig(default_tools=("bash",))
    eng = Engine(cfg=cfg, workdir=pathlib.Path(tempfile.mkdtemp()))
    names = {t.name() for t in eng.tools.list()}
    assert "bash" in names
    assert "write_artifact" not in names
    assert "delegate" in names  # 引擎级工具不受 default_tools 过滤（delegate 后置注册）


def test_retry_and_timeout_configurable():
    """配置补遗：llm_max_retries/llm_timeout 配置化（P12 定案 4 次硬编码 → 可调）。"""
    import pathlib
    import tempfile

    from wuxing.config import EngineConfig
    from wuxing.engine import Engine
    cfg = EngineConfig(router={"plan": "deepseek:deepseek-chat"},
                       llm_max_retries=7, llm_timeout=99.0)
    eng = Engine(cfg=cfg, workdir=pathlib.Path(tempfile.mkdtemp()))
    p = eng.router.for_domain("plan")
    assert p.max_retries == 7
    assert p.max_retries != 4  # 不再硬编码


def test_field_spec_defaults_match_config_ssot():
    """A4：FIELD_SPECS 默认值与 EngineConfig（SSOT）全等——双写纪律守卫生效。

    此前 max_unit_budget(5vs3)/llm_timeout(180vs60)/default_tools(缺load_skill)
     不一致——配置文件中未覆盖字段时 schema 描述与真实行为背离。
    """
    import dataclasses

    from wuxing.config import EngineConfig
    from wuxing.config_schema import FIELD_SPECS

    def cfg_default(f):
        if f.default is not dataclasses.MISSING:
            return f.default
        return f.default_factory()

    cfg_defaults = {f.name: cfg_default(f) for f in dataclasses.fields(EngineConfig)}
    spec_map = {s.name: s for s in FIELD_SPECS}
    for name, s in spec_map.items():
        assert name in cfg_defaults, f"schema 有字段 {name} 但 dataclass 无"
        expect = cfg_defaults[name]
        if isinstance(expect, tuple):
            assert tuple(s.default or ()) == expect, \
                f"{name}: schema 默认 {s.default} != SSOT {expect}"
        elif isinstance(expect, dict):
            assert (s.default or {}) == expect, \
                f"{name}: schema 默认 {s.default} != SSOT {expect}"
        else:
            assert s.default == expect, \
                f"{name}: schema 默认 {s.default} != SSOT {expect}"
    for name in cfg_defaults:
        assert name in spec_map, f"dataclass 字段 {name} 无 schema 声明（双写缺失）"


def test_ui_theme_field_declared():
    """双主题（2026-09-19 用户裁决）：ui_theme ∈ {ink, plain}，默认 ink；config 与 schema 双写一致。"""
    from wuxing.config import EngineConfig
    from wuxing.config_schema import FIELD_SPECS, validate_config
    spec = next((s for s in FIELD_SPECS if s.name == "ui_theme"), None)
    assert spec is not None, "ui_theme 未声明"
    assert spec.type == "str"
    assert spec.default == "ink"
    assert set(spec.enum or ()) == {"ink", "plain"}
    assert EngineConfig().ui_theme == "ink"
    assert validate_config({"ui_theme": "plain"}) == []
    assert validate_config({"ui_theme": "ink"}) == []
    assert validate_config({"ui_theme": "neon"}), "非法主题应报错"
