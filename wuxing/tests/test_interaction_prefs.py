"""#2 Phase 1.5：交互偏好两级存档（默认/合并/损坏/校验/写回）。"""
import json

from wuxing import interaction_prefs


def _patch(tmp_path, monkeypatch):
    user = tmp_path / "user.json"
    ws = tmp_path / "ws.json"
    monkeypatch.setattr(interaction_prefs, "user_store_path", lambda: user)
    monkeypatch.setattr(interaction_prefs, "workspace_store_path",
                        lambda root: ws)
    return user, ws


def _eff(ws_root):
    got = interaction_prefs.load_effective(ws_root)
    return got["values"], got["problems"]


def test_defaults_when_missing(tmp_path, monkeypatch):
    _patch(tmp_path, monkeypatch)
    values, problems = _eff(tmp_path / "proj")
    assert values == {"confirm_verbosity": "standard",
                      "details_default_open": False,
                      "remember_details_choice": True,
                      "confirm_notify": False}
    assert problems == []


def test_workspace_overrides_user(tmp_path, monkeypatch):
    user, _ = _patch(tmp_path, monkeypatch)
    user.write_text(json.dumps({"version": 1, "prefs": {
        "confirm_verbosity": "concise", "details_default_open": True}}),
        encoding="utf-8")
    values, _ = _eff(tmp_path / "proj")            # 工作区缺失 → 用户级生效
    assert values["confirm_verbosity"] == "concise"
    assert values["details_default_open"] is True
    interaction_prefs.save_scope("workspace", tmp_path / "proj",
                                 {"confirm_verbosity": "standard"})
    values, _ = _eff(tmp_path / "proj")            # 工作区覆盖用户
    assert values["confirm_verbosity"] == "standard"
    assert values["details_default_open"] is True  # 逐字段：未覆盖项仍回退用户


def test_corrupt_store_fail_closed(tmp_path, monkeypatch):
    user, _ = _patch(tmp_path, monkeypatch)
    user.write_text("{bad", encoding="utf-8")
    values, problems = _eff(tmp_path / "proj")
    assert values["confirm_verbosity"] == "standard"
    assert problems, "损坏必须留诊断"
    assert "读取失败" in problems[0]


def test_validate_and_save_roundtrip(tmp_path, monkeypatch):
    _patch(tmp_path, monkeypatch)
    errors = interaction_prefs.validate_values(
        {"confirm_verbosity": "fancy"})
    assert errors and "confirm_verbosity" in errors[0]
    errors = interaction_prefs.validate_values(
        {"details_default_open": "yes"})
    assert errors
    _, errors = interaction_prefs.save_scope(
        "user", None, {"confirm_verbosity": "concise",
                       "details_default_open": True})
    assert errors == []
    values, _ = _eff(None)
    assert values["confirm_verbosity"] == "concise"
    assert values["details_default_open"] is True
    # None=删除字段回退默认
    interaction_prefs.save_scope("user", None,
                                 {"details_default_open": None})
    values, _ = _eff(None)
    assert values["details_default_open"] is False


def test_all_effective_reports_sources(tmp_path, monkeypatch):
    user, _ = _patch(tmp_path, monkeypatch)
    user.write_text(json.dumps({"version": 1, "prefs": {
        "remember_details_choice": False}}), encoding="utf-8")
    data = interaction_prefs.all_effective(tmp_path / "proj")
    assert data["effective"]["remember_details_choice"] is False
    assert data["sources"]["remember_details_choice"] == "user"
    assert data["sources"]["confirm_verbosity"] == "default"


def test_confirm_notify_validate_and_roundtrip(tmp_path, monkeypatch):
    _patch(tmp_path, monkeypatch)
    errors = interaction_prefs.validate_values({"confirm_notify": "yes"})
    assert errors, "非布尔必须拒绝"
    _, errors = interaction_prefs.save_scope(
        "user", None, {"confirm_notify": True})
    assert errors == []
    values, _ = _eff(None)
    assert values["confirm_notify"] is True
    interaction_prefs.save_scope("user", None, {"confirm_notify": None})
    values, _ = _eff(None)
    assert values["confirm_notify"] is False   # None=删除字段回退默认


def test_confirm_notify_workspace_overrides_user(tmp_path, monkeypatch):
    user, _ = _patch(tmp_path, monkeypatch)
    user.write_text(json.dumps({"version": 1, "prefs": {
        "confirm_notify": True}}), encoding="utf-8")
    values, _ = _eff(tmp_path / "proj")
    data = interaction_prefs.all_effective(tmp_path / "proj")
    assert values["confirm_notify"] is True
    assert data["sources"]["confirm_notify"] == "user"
    interaction_prefs.save_scope("workspace", tmp_path / "proj",
                                 {"confirm_notify": False})
    values, _ = _eff(tmp_path / "proj")
    assert values["confirm_notify"] is False
