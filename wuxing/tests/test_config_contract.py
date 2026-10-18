"""TDD：配置读写契约（UI 重构阶段 3 · 引擎对齐项⑨）——壳设置中心的唯一入口。

- describe_config：字段声明（含生效范围 scope）
- effective_config：三层生效值 + 来源（default / user / workspace）
- write_config：写入用户级（~/.wuxing/config.jsonc）或工作区级（<workdir>/.wuxing/config.jsonc）
"""
import json

import pytest

import wuxing.config_contract as cc


def test_describe_config_lists_fields_with_scope():
    desc = cc.describe_config()
    names = {d["name"] for d in desc}
    assert {"max_loop_rounds", "fsc_enabled", "sandbox_enabled"} <= names
    by_name = {d["name"]: d for d in desc}
    assert by_name["max_loop_rounds"]["scope"] in ("now", "next", "restart")
    assert by_name["max_loop_rounds"]["desc"]  # 说明随声明提供


def test_effective_values_report_source(tmp_path, monkeypatch):
    user_cfg = tmp_path / "user.jsonc"
    user_cfg.write_text('{"max_loop_rounds": 9}', encoding="utf-8")
    monkeypatch.setattr(cc, "user_config_path", lambda: user_cfg)
    wd = tmp_path / "proj"
    wd.mkdir()
    eff = cc.effective_config(wd)
    assert eff["values"]["max_loop_rounds"] == 9
    assert eff["sources"]["max_loop_rounds"] == "user"
    assert eff["sources"]["fsc_enabled"] == "default"

    ws_cfg = wd / ".wuxing" / "config.jsonc"
    ws_cfg.parent.mkdir()
    ws_cfg.write_text('{"max_loop_rounds": 7}', encoding="utf-8")
    eff2 = cc.effective_config(wd)
    assert eff2["values"]["max_loop_rounds"] == 7
    assert eff2["sources"]["max_loop_rounds"] == "workspace"


def test_write_config_validates_and_persists(tmp_path, monkeypatch):
    user_cfg = tmp_path / "user.jsonc"
    monkeypatch.setattr(cc, "user_config_path", lambda: user_cfg)
    wd = tmp_path / "proj"
    wd.mkdir()
    out = cc.write_config("user", {"max_loop_rounds": 5})
    assert out["ok"] is True and "max_loop_rounds" in out["written"]
    assert cc.effective_config(wd)["values"]["max_loop_rounds"] == 5
    with pytest.raises(cc.ConfigError):
        cc.write_config("user", {"max_loop_rounds": "not-an-int"})
    with pytest.raises(cc.ConfigError):
        cc.write_config("user", {"no_such_field": 1})
    with pytest.raises(cc.ConfigError):
        cc.write_config("badscope", {"max_loop_rounds": 5})


def test_write_workspace_scope_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(cc, "user_config_path",
                        lambda: tmp_path / "user.jsonc")
    wd = tmp_path / "proj"
    wd.mkdir()
    cc.write_config("workspace", {"max_loop_rounds": 3}, workdir=wd)
    cfg = wd / ".wuxing" / "config.jsonc"
    assert cfg.is_file()
    assert json.loads(cfg.read_text(encoding="utf-8"))["max_loop_rounds"] == 3
    eff = cc.effective_config(wd)
    assert eff["sources"]["max_loop_rounds"] == "workspace"


def test_write_config_merges_existing(tmp_path, monkeypatch):
    """写入不覆盖同层其他键（merge 语义）。"""
    user_cfg = tmp_path / "user.jsonc"
    user_cfg.write_text('{"max_loop_rounds": 9, "fsc_enabled": false}',
                        encoding="utf-8")
    monkeypatch.setattr(cc, "user_config_path", lambda: user_cfg)
    cc.write_config("user", {"max_loop_rounds": 4})
    data = json.loads(user_cfg.read_text(encoding="utf-8"))
    assert data["max_loop_rounds"] == 4
    assert data["fsc_enabled"] is False, "同层其他键必须保留"


def test_effective_config_without_workspace_uses_user_layer(tmp_path, monkeypatch):
    """无打开工作区时（workdir=None）仍返回用户级 + 默认（设置中心不依赖工作区）。"""
    user_cfg = tmp_path / "user.jsonc"
    user_cfg.write_text('{"max_loop_rounds": 8}', encoding="utf-8")
    monkeypatch.setattr(cc, "user_config_path", lambda: user_cfg)
    eff = cc.effective_config(None)
    assert eff["values"]["max_loop_rounds"] == 8
    assert eff["sources"]["max_loop_rounds"] == "user"
    assert eff["sources"]["fsc_enabled"] == "default"


def test_write_config_replace_keys(tmp_path, monkeypatch):
    """replace_keys：字典型字段整体替换（支持删除条目）；默认仍为 merge。"""
    monkeypatch.setattr(cc, "user_config_path", lambda: tmp_path / "user.jsonc")
    cc.write_config("user", {"context_tool_limits": {"read_file": 1, "bash": 2}})
    cc.write_config("user", {"context_tool_limits": {"bash": 3}})   # merge：read_file 保留
    eff = cc.effective_config(None)
    assert eff["values"]["context_tool_limits"] == {"read_file": 1, "bash": 3}
    cc.write_config("user", {"context_tool_limits": {"bash": 3}},
                    replace_keys=["context_tool_limits"])
    eff2 = cc.effective_config(None)
    assert eff2["values"]["context_tool_limits"] == {"bash": 3}
