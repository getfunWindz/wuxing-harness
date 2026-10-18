"""TDD：#3 域提示词——两层存档/逐字段合并/校验（设计 §2）。"""
import json

import pytest

from wuxing import domain_prompts


@pytest.fixture()
def stores(tmp_path, monkeypatch):
    user = tmp_path / "user.json"
    ws = tmp_path / "ws.json"
    monkeypatch.setattr(domain_prompts, "user_store_path", lambda: user)
    monkeypatch.setattr(domain_prompts, "workspace_store_path", lambda root: ws)
    return user, ws


def _write(path, domains):
    path.write_text(json.dumps({"version": 1, "domains": domains},
                               ensure_ascii=False), encoding="utf-8")


def test_missing_store_defaults(stores):
    eff = domain_prompts.load_effective("/tmp/x", "verify")
    assert eff["notes"] == "" and eff["addendum"] == ""
    assert eff["notes_source"] == "default" and eff["addendum_source"] == "none"
    assert eff["problems"] == []


def test_workspace_overrides_user_per_field(stores):
    user, ws = stores
    _write(user, {"verify": {"notes": "用户注记", "addendum": "用户补充"}})
    _write(ws, {"verify": {"addendum": "工作区补充"}})
    eff = domain_prompts.load_effective("/tmp/x", "verify")
    assert eff["notes"] == "用户注记" and eff["notes_source"] == "user"
    assert eff["addendum"] == "工作区补充" and eff["addendum_source"] == "workspace"


def test_corrupt_store_fail_closed(stores):
    user, _ = stores
    user.write_text("{bad json", encoding="utf-8")
    eff = domain_prompts.load_effective("/tmp/x", "verify")
    assert eff["notes"] == "" and eff["problems"], "损坏必须空档+注记"


def test_unknown_domain_and_oversize_problem(stores):
    user, _ = stores
    _write(user, {"nope": {"notes": "x"},
                  "plan": {"notes": "y" * (domain_prompts.MAX_SEGMENT_CHARS + 1)}})
    eff = domain_prompts.load_effective("/tmp/x", "plan")
    assert eff["notes"] == "" and len(eff["problems"]) == 2


def test_save_scope_roundtrip_and_clear(stores):
    assert "verify" in domain_prompts.DOMAIN_IDS and "design" in domain_prompts.DOMAIN_IDS
    _, errors = domain_prompts.save_scope(
        "user", "/tmp/x", {"verify": {"notes": "A", "addendum": "B"}})
    assert errors == []
    eff = domain_prompts.load_effective("/tmp/x", "verify")
    assert eff["notes"] == "A" and eff["addendum"] == "B"
    # 空串=清除回退
    _, errors = domain_prompts.save_scope("user", "/tmp/x", {"verify": {"notes": ""}})
    assert errors == []
    eff = domain_prompts.load_effective("/tmp/x", "verify")
    assert eff["notes"] == "" and eff["addendum"] == "B"


def test_save_scope_rejects_oversize_and_unknown(stores):
    _, errors = domain_prompts.save_scope(
        "user", "/tmp/x",
        {"verify": {"notes": "y" * (domain_prompts.MAX_SEGMENT_CHARS + 1)},
         "nope": {"notes": "x"}})
    assert len(errors) == 2


def test_all_effective_lists_five_domains(stores):
    entries, problems = domain_prompts.all_effective("/tmp/x")
    assert [e["domain"] for e in entries] == ["plan", "execute", "verify",
                                              "user", "design"]
    assert entries[2]["builtin_notes"], "内置默认注记必须可见"
    assert problems == []
