"""TDD：FSC 配置双写 + 启用接线 + 报告观测。"""
import pathlib
import tempfile


def test_fsc_config_defaults_and_schema_consistent():
    from wuxing.config import EngineConfig
    from wuxing.config_schema import FIELD_SPECS
    c = EngineConfig()
    assert c.fsc_enabled is True, "用户裁决 2026-09-12：FSC 默认开（用户自主关闭）"
    assert c.fsc_retention_rounds == 4
    # 方案2（用户裁决 2026-09-12）：精确键语义——阈值死配置必须移除
    assert not hasattr(c, "fsc_match_threshold"), \
        "fsc_match_threshold 已废弃（精确键——设计修订 2026-09-12）"
    names = {s.name for s in FIELD_SPECS}
    for k in ("fsc_enabled", "fsc_retention_rounds",
              "fsc_max_session_chars", "fsc_max_reuse", "fsc_total_char_budget"):
        assert k in names, k
    assert "fsc_match_threshold" not in names, "schema 同步移除（双写纪律）"


def test_fsc_default_on_and_fallback_params():
    """默认开 + 低匹配回退参数（用户裁决 2026-09-12）——双写纪律。"""
    from wuxing.config import EngineConfig
    from wuxing.config_schema import FIELD_SPECS
    c = EngineConfig()
    assert c.fsc_enabled is True
    assert c.fsc_fallback_digest is True, "低匹配回退默认开"
    assert c.fsc_digest_max_chars == 7000, \
        "2026-09-23 全局上限放宽（2000→7000——双模式批 1）"
    names = {s.name for s in FIELD_SPECS}
    for k in ("fsc_fallback_digest", "fsc_digest_max_chars"):
        assert k in names, k
    spec_map = {s.name: s for s in FIELD_SPECS}
    assert spec_map["fsc_enabled"].default is True, "schema 默认值同步"


def test_engine_fsc_wiring():
    from wuxing.config import EngineConfig
    from wuxing.engine import Engine
    eng = Engine(cfg=EngineConfig(fsc_enabled=True),
                 workdir=pathlib.Path(tempfile.mkdtemp()), auto_confirm=True)
    assert eng.orchestrator.session_pool is not None
    st = eng.orchestrator.session_pool.stats()
    assert "pool_size" in st and "reused" in st
    eng2 = Engine(cfg=EngineConfig(fsc_enabled=False),
                  workdir=pathlib.Path(tempfile.mkdtemp()), auto_confirm=True)
    assert eng2.orchestrator.session_pool is None


def test_run_profile_fsc_report_stats():
    import json

    from wuxing.real_test import run_profile
    wd = pathlib.Path(tempfile.mkdtemp())
    run_profile("precise", workdir=wd, llm=None, real_shape=False,
                max_turns=1, fsc=True)
    summary = json.loads((wd / "real_test_report.json").read_text(
        encoding="utf-8"))["summary"]
    assert "fsc" in summary, "启用 FSC 时摘要必须含池统计"
    assert "pool_size" in summary["fsc"]
    assert "keyed" in summary["fsc"], "键覆盖率口径必须进报告（A2）"
    assert "unkeyed" in summary["fsc"], "键覆盖率口径必须进报告（A2）"
    row = json.loads((wd / "real_test_report.json").read_text(
        encoding="utf-8"))["turns"][0]
    assert "fsc_reused" in row, "轮级报告必须含复用计数"


def test_mock_plan_emits_workstream_label():
    """mock 计划契约（A2）：输出含『工作流：』标注（与真实 plan prompt 契约一致）——
    供 mock 端到端键覆盖率验收（注入→键→匹配链路可用）。"""
    from wuxing.llm.mock import MockLlmProvider
    out = MockLlmProvider().chat([{"role": "system", "content": "域：plan"}])
    text = str(getattr(out, "text", out))
    assert "工作流：" in text, text
