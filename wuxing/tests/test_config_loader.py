import pathlib
import tempfile

from wuxing.config_loader import ConfigError, load_config, merge_configs, parse_jsonc


def test_parse_jsonc_with_comments():
    raw = '''
    {
      // 全局护栏
      "max_loop_rounds": 8,  /* 注释 */
      "llm": "deepseek:deepseek-chat"
    }
    '''
    data = parse_jsonc(raw)
    assert data["max_loop_rounds"] == 8
    assert data["llm"] == "deepseek:deepseek-chat"

def test_merge_non_conflicting_preserved():
    a = {"max_loop_rounds": 5, "llm": "mock"}
    b = {"confirm_threshold": 1.0}
    merged = merge_configs(a, b)
    assert merged["max_loop_rounds"] == 5  # 无冲突保留
    assert merged["confirm_threshold"] == 1.0
    assert merged["llm"] == "mock"

def test_merge_conflict_later_wins():
    a = {"max_loop_rounds": 5}
    b = {"max_loop_rounds": 8}
    assert merge_configs(a, b)["max_loop_rounds"] == 8

def test_load_three_layers():
    with tempfile.TemporaryDirectory() as tmp:
        wd = pathlib.Path(tmp)
        # 全局层（用临时 HOME 避免污染——monkeypatch 场景简化：直接写全局路径测试独立）
        global_dir = pathlib.Path(tmp) / "home" / ".wuxing"
        global_dir.mkdir(parents=True)
        (global_dir / "config.jsonc").write_text(
            '{"max_loop_rounds": 10, "llm": "mock"}', encoding="utf-8")
        # 项目层
        (wd / ".wuxing").mkdir()
        (wd / ".wuxing" / "config.jsonc").write_text(
            '{"confirm_threshold": 0.5}', encoding="utf-8")
        # 工作区层
        (wd / "config.jsonc").write_text(
            '{"max_parallel_units": 4}', encoding="utf-8")
        merged = load_config(wd, global_config_dir=global_dir)
        assert merged["max_loop_rounds"] == 10  # 全局
        assert merged["confirm_threshold"] == 0.5  # 项目
        assert merged["max_parallel_units"] == 4  # 工作区

def test_load_invalid_raises_early():
    with tempfile.TemporaryDirectory() as tmp:
        wd = pathlib.Path(tmp)
        (wd / "config.jsonc").write_text('{"max_loop_rounds": "bad"}', encoding="utf-8")
        try:
            load_config(wd)
            assert False
        except ConfigError as e:
            assert "max_loop_rounds" in str(e)


# ===== 配置标准整改（阶段 2）：parse_jsonc 边界与 schema 一致性 =====

def test_parse_jsonc_url_in_string_not_mangled():
    # 字符串内含 //（URL）不得被当注释
    raw = '{"url": "https://api.deepseek.com/v1", "x": 1}'
    assert parse_jsonc(raw)["url"] == "https://api.deepseek.com/v1"

def test_parse_jsonc_comment_markers_in_string():
    # 字符串内含 /* 与 */ 不误删
    raw = '{"a": "/*not a comment*/", "b": "// still string"}'
    assert parse_jsonc(raw) == {"a": "/*not a comment*/", "b": "// still string"}

def test_parse_jsonc_bom_and_crlf():
    raw = '\ufeff{\r\n  "llm": "mock" // 行尾注释\r\n}\r\n'
    assert parse_jsonc(raw) == {"llm": "mock"}

def test_parse_jsonc_block_comment_multiline():
    raw = '/*\n多行注释\n*/\n{"router": {"_default": "mock"}}'
    assert parse_jsonc(raw) == {"router": {"_default": "mock"}}

def test_parse_jsonc_line_comment_with_quotes():
    # P11 修复回归：行注释内含引号（// "router": {...}）不得污染字符串状态
    raw = '{"llm": "mock"} // "router": {"plan": "x"}'
    assert parse_jsonc(raw) == {"llm": "mock"}

def test_parse_jsonc_unterminated_block_comment_raises():
    # 未闭合块注释：显式失败（不静默吞内容）
    import pytest
    with pytest.raises(Exception):
        parse_jsonc('{"a": 1} /* never closed')

def test_parse_jsonc_trailing_comma_rejected():
    # 尾逗号不静默通过（JSONC 标准不允许——opencode 风格严格）
    import pytest
    with pytest.raises(Exception):
        parse_jsonc('{"a": 1,}')

def test_config_and_schema_stay_in_sync():
    """配置纪律机械保证（阶段 2）：EngineConfig 字段集 == FIELD_SPECS 字段集。
    双写漂移是『配置阶段大量问题』的根源之一——从此自动化守卫。"""
    import dataclasses

    from wuxing.config import EngineConfig
    from wuxing.config_schema import FIELD_SPECS
    cfg_fields = {f.name for f in dataclasses.fields(EngineConfig)}
    spec_fields = {s.name for s in FIELD_SPECS}
    assert cfg_fields == spec_fields, \
        f"双写漂移：仅config={cfg_fields - spec_fields} 仅schema={spec_fields - cfg_fields}"


def test_load_config_global_dir_hook(tmp_path, monkeypatch):
    """全局配置目录经 _global_config_dir 钩子解析——测试隔离点（防真实用户配置泄漏）。"""
    from wuxing import config_loader as cl
    g = tmp_path / "g"
    g.mkdir()
    (g / "config.jsonc").write_text('{"max_loop_rounds": 9}', encoding="utf-8")
    monkeypatch.setattr(cl, "_global_config_dir", lambda: g)
    wd = tmp_path / "wd"
    wd.mkdir()
    data = cl.load_config(wd)
    assert data["max_loop_rounds"] == 9
