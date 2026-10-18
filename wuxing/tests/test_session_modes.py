"""TDD（双模式批 1 · Task 2）：模式对象与 sidecar（session-modes）。

依据：docs/plans/2026-09-23-wuxing-dual-mode-batch1.md Task 2 + 设计 §3/§8。
sidecar 格式：{"version":1,"conversations":{"<name>":{"mode","variant","ts"}}}。
"""
import json

import pytest


def test_parse_id_known_and_unknown():
    from wuxing.session_modes import parse_id
    assert parse_id("minimal-pure") == {"mode": "minimal", "variant": "pure"}
    assert parse_id("minimal-standard") == {"mode": "minimal",
                                            "variant": "standard"}
    assert parse_id("theroad") == {"mode": "theroad", "variant": ""}
    assert parse_id("wayfinder") == {"mode": "theroad", "variant": ""}  # 旧值兼容读
    for bad in ("", "minimal", "minimal-nope", "wayfinder-pure", "nope", None):
        with pytest.raises(ValueError):
            parse_id(bad)


def test_resolve_default_and_session_override(tmp_path):
    from wuxing.session_modes import resolve, save
    r0 = resolve(tmp_path)
    assert (r0["mode"], r0["variant"], r0["source"]) == ("minimal", "standard",
                                                         "default")
    save(tmp_path, "conversation-1.jsonl", "minimal", "pure")
    r = resolve(tmp_path, conversation="conversation-1.jsonl")
    assert (r["mode"], r["variant"], r["source"]) == ("minimal", "pure",
                                                      "session")
    # 其他会话不受影响；自定义默认生效
    assert resolve(tmp_path, conversation="other.jsonl")["source"] == "default"
    r2 = resolve(tmp_path, conversation="other.jsonl", default="minimal-pure")
    assert (r2["mode"], r2["variant"], r2["source"]) == ("minimal", "pure",
                                                         "default")


def test_save_rejects_unknown_and_corrupt_load(tmp_path):
    from wuxing.session_modes import load, resolve, save
    with pytest.raises(ValueError):
        save(tmp_path, "c.jsonl", "nope", "pure")
    with pytest.raises(ValueError):
        save(tmp_path, "c.jsonl", "minimal", "nope")
    with pytest.raises(ValueError):
        save(tmp_path, "", "minimal", "pure")
    p = tmp_path / ".wuxing" / "session-modes.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{broken", encoding="utf-8")
    assert load(tmp_path) == {}
    assert resolve(tmp_path)["source"] == "default"  # 损坏不 raise


def test_theroad_variant_normalized(tmp_path):
    from wuxing.session_modes import resolve, save
    entry = save(tmp_path, "w.jsonl", "theroad", "pure")
    assert entry["variant"] == "" and entry["mode"] == "theroad"
    r = resolve(tmp_path, conversation="w.jsonl")
    assert (r["mode"], r["variant"], r["source"]) == ("theroad", "", "session")
    # 旧值写入也归一为新值（写侧新值纪律）
    save(tmp_path, "w2.jsonl", "wayfinder", "")
    assert resolve(tmp_path, conversation="w2.jsonl")["mode"] == "theroad"


def test_legacy_wayfinder_sidecar_read_normalized(tmp_path):
    """旧 sidecar（批 1 前写入的 wayfinder）读侧归一为 theroad。"""
    p = tmp_path / ".wuxing" / "session-modes.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"version": 1, "conversations": {
        "old.jsonl": {"mode": "wayfinder", "variant": "", "ts": 1.0}}}),
        encoding="utf-8")
    from wuxing.session_modes import resolve
    r = resolve(tmp_path, conversation="old.jsonl")
    assert (r["mode"], r["variant"], r["source"]) == ("theroad", "", "session")


def test_sidecar_structure_and_merge(tmp_path):
    from wuxing.session_modes import load, save
    save(tmp_path, "c.jsonl", "minimal", "standard")
    data = load(tmp_path)
    assert data["version"] == 1
    row = data["conversations"]["c.jsonl"]
    assert row["mode"] == "minimal" and row["variant"] == "standard"
    assert isinstance(row["ts"], (int, float))
    assert not (tmp_path / ".wuxing" / "session-modes.json.tmp").exists()
    save(tmp_path, "d.jsonl", "minimal", "pure")
    data2 = load(tmp_path)
    assert set(data2["conversations"]) == {"c.jsonl", "d.jsonl"}


def test_conversation_is_blank(tmp_path):
    from wuxing.conversation import ConversationState
    from wuxing.session_modes import conversation_is_blank
    p = tmp_path / "c.jsonl"
    assert conversation_is_blank(p) is True
    st = ConversationState(p)
    st.append_turn(1, "需求", [], "完成")
    assert conversation_is_blank(p) is False


def test_resolve_ignores_invalid_session_entry(tmp_path):
    """sidecar 条目损坏/未知值 → 回落默认（读侧容错，不 raise）。"""
    from wuxing.session_modes import resolve
    p = tmp_path / ".wuxing" / "session-modes.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"version": 1, "conversations": {
        "bad.jsonl": {"mode": "bogus", "variant": "???"}}}), encoding="utf-8")
    r = resolve(tmp_path, conversation="bad.jsonl")
    assert r["source"] == "default"
