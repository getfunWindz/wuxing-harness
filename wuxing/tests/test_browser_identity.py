"""TDD · O2-2 §11.5-①：身份键/模式/注册表读取。"""
import json
import os

from wuxing import browser_identity


def test_identity_key_stable_and_workspace_scoped(tmp_path):
    a = tmp_path / "proj-a"; a.mkdir()
    b = tmp_path / "proj-b"; b.mkdir()
    k1 = browser_identity.identity_key(a)
    assert k1 == browser_identity.identity_key(a)
    assert k1 != browser_identity.identity_key(b)
    assert k1.startswith("wuxing-browser-")
    assert len(k1) == len("wuxing-browser-") + 16


def test_identity_key_case_insensitive_on_windows(tmp_path):
    """normcase 规范化：Windows 下同路径不同大小写 → 同键。"""
    (tmp_path / "proj").mkdir()
    p = str(tmp_path / "proj")
    alt = p.replace("proj", "PROJ")
    if os.name == "nt":
        assert browser_identity.identity_key(p) == \
            browser_identity.identity_key(alt)
    else:
        assert browser_identity.identity_key(p) == \
            browser_identity.identity_key(p)


class _Cfg:
    def __init__(self, mode="memory"):
        self.browser_identity_mode = mode


def test_identity_for_modes(tmp_path):
    ident = browser_identity.identity_for(_Cfg("memory"), tmp_path)
    assert ident["mode"] == "memory"
    assert ident["key"] == browser_identity.identity_key(tmp_path)
    assert ident["workspace"]
    assert browser_identity.identity_for(_Cfg("persist"), tmp_path)["mode"] \
        == "persist"


def test_identity_for_invalid_mode_fail_closed(tmp_path):
    assert browser_identity.identity_for(_Cfg("wat"), tmp_path)["mode"] \
        == "memory"
    assert browser_identity.identity_for(_Cfg(""), tmp_path)["mode"] \
        == "memory"


def test_session_overlay_memory_key(tmp_path):
    """Q1=B：memory 档键 = 基键 + 会话 overlay（稳定、可区分）。"""
    base = browser_identity.identity_key(tmp_path)
    a = browser_identity.identity_for(_Cfg("memory"), tmp_path,
                                      session="sess-a")
    b = browser_identity.identity_for(_Cfg("memory"), tmp_path,
                                      session="sess-b")
    assert a["key"].startswith(base + "-")
    assert a["key"] != b["key"]
    assert browser_identity.identity_for(
        _Cfg("memory"), tmp_path, session="sess-a")["key"] == a["key"]
    assert len(browser_identity.session_token("sess-a")) == 8
    assert browser_identity.session_token("") == ""


def test_persist_key_ignores_session(tmp_path):
    """Q2=A：persist 档保持工作区级（忽略会话 overlay）。"""
    base = browser_identity.identity_key(tmp_path)
    ident = browser_identity.identity_for(_Cfg("persist"), tmp_path,
                                          session="sess-a")
    assert ident["key"] == base
    assert ident["mode"] == "persist"


def test_no_session_zero_change(tmp_path):
    """无会话（headless/测试）→ 基键，零行为变化。"""
    assert browser_identity.identity_for(_Cfg("memory"), tmp_path)["key"] \
        == browser_identity.identity_key(tmp_path)
    assert browser_identity.identity_for(
        _Cfg("memory"), tmp_path, session="")["key"] \
        == browser_identity.identity_key(tmp_path)


def test_anchor_prefers_manifest_root(tmp_path):
    """D1：worktree run（manifest_root=主工作区）→ 基键锚定真实工作区。"""
    class _Ws:
        root = tmp_path / "worktree"
        manifest_root = tmp_path / "main"

    _Ws.root.mkdir()
    _Ws.manifest_root.mkdir()
    got = browser_identity.anchor_of(_Ws())
    assert str(got) == str(_Ws.manifest_root)
    assert browser_identity.identity_for(_Cfg("memory"), got)["key"] \
        == browser_identity.identity_key(_Ws.manifest_root)
    # 普通 ws（无 manifest_root）→ root 兜底
    class _Plain:
        root = tmp_path / "plain"

    assert str(browser_identity.anchor_of(_Plain())) == str(_Plain.root)


def test_registry_read_fail_closed(tmp_path, monkeypatch):
    reg = tmp_path / "browser_identities.json"
    monkeypatch.setattr(browser_identity, "registry_path", lambda: reg)
    assert browser_identity.read_registry() == ([], [])
    reg.write_text("{bad", encoding="utf-8")
    entries, problems = browser_identity.read_registry()
    assert entries == [] and problems
    reg.write_text(json.dumps({"version": 1, "entries": [
        {"key": "wuxing-browser-x", "workspace": "C:/p", "mode": "persist",
         "first_used_at": "T1", "last_used_at": "T2"}]}), encoding="utf-8")
    entries, problems = browser_identity.read_registry()
    assert problems == []
    assert entries[0]["key"] == "wuxing-browser-x"
    assert entries[0]["last_used_at"] == "T2"


# ---- O2-2 §11.5-③：storage-state 登录态档（Q4=A/D5-D8） ----


def _sstate_cfg(path):
    cfg = _Cfg("storage-state")
    cfg.browser_storage_state_path = str(path)
    return cfg


def test_storage_state_key_and_payload(tmp_path):
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"cookies": [{"name": "a", "value": "b",
                     "domain": "127.0.0.1", "path": "/"}], "origins": []}),
                     encoding="utf-8")
    cfg = _sstate_cfg(state)
    ident = browser_identity.identity_for(cfg, tmp_path, session="sess-a")
    base = browser_identity.identity_key(tmp_path)
    assert ident["mode"] == "storage-state"
    assert ident["state_path"] == str(state)
    assert ident["key"].startswith(base + "-")
    assert ident["key"].count("-") == base.count("-") + 2   # session8 + state8
    assert "state_error" not in ident
    # 内容/mtime 变换 → state8 变换（键变 → 下次命令重建重注入）
    state.write_text(json.dumps({"cookies": [], "origins": [
        {"origin": "http://x", "localStorage": [{"name": "k",
         "value": "v"}]}]}), encoding="utf-8")
    ident2 = browser_identity.identity_for(cfg, tmp_path, session="sess-a")
    assert ident2["key"] != ident["key"]
    assert "state_error" not in ident2


def test_storage_state_invalid_fail_closed(tmp_path):
    cfg = _sstate_cfg("")
    assert browser_identity.identity_for(cfg, tmp_path)["state_error"]
    assert browser_identity.identity_for(
        _sstate_cfg(tmp_path / "nope.json"), tmp_path)["state_error"]
    bad = tmp_path / "bad.json"
    bad.write_text("{bad", encoding="utf-8")
    assert browser_identity.identity_for(
        _sstate_cfg(bad), tmp_path)["state_error"]
    empty = tmp_path / "empty.json"
    empty.write_text('{"cookies": [], "origins": []}', encoding="utf-8")
    assert browser_identity.identity_for(
        _sstate_cfg(empty), tmp_path)["state_error"]


def test_storage_state_size_limit(tmp_path):
    big = tmp_path / "big.json"
    big.write_text("x" * (browser_identity.MAX_STATE_BYTES + 1),
                   encoding="utf-8")
    s = browser_identity.storage_state_summary(_sstate_cfg(big))
    assert s["valid"] is False and "超限" in s["error"]


def test_storage_state_summary_counts(tmp_path):
    state = tmp_path / "s.json"
    state.write_text(json.dumps({"cookies": [{"name": "a", "value": "b",
        "domain": "127.0.0.1", "path": "/"}], "origins": [
        {"origin": "http://127.0.0.1:1", "localStorage": [
            {"name": "k", "value": "v"}]}]}), encoding="utf-8")
    s = browser_identity.storage_state_summary(_sstate_cfg(state))
    assert s["valid"] is True and s["cookies"] == 1 and s["origins"] == 1
    assert s["error"] == "" and len(s["token"]) == 8
    # 值纪律：摘要只含计数/路径/token，不得出现任何 cookie/localStorage 值
    dumped = json.dumps(s, ensure_ascii=False)
    assert "\"b\"" not in dumped and "\"v\"" not in dumped


def test_mode_unknown_still_fail_closed_memory(tmp_path):
    assert browser_identity.identity_for(_Cfg("wat"), tmp_path)["mode"] \
        == "memory"
