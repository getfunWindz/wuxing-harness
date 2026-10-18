"""C2（第二轮计划 §2 · 评估 P1）：技能自进化收益台账。

事件侧车 ``<skills>/../state/<name>/usage.jsonl``（loaded/evolved）→ 机械报表
（触发/复用/闲置）→ 淘汰建议（长期零复用；归档动作显式调用，不自动删除）。
P3（2026-10-18）：sidecar 收敛 state/；旧 ``.usage.jsonl`` / ``_archived/`` 兼容读。
"""
import pathlib

import pytest

from wuxing.skill_ledger import (
    archive_skill,
    ledger_path,
    ledger_report,
    list_skills,
    read_events,
    record_event,
    unused_candidates,
)


@pytest.fixture
def skills(tmp_path):
    root = tmp_path / "skills"
    root.mkdir()
    return root


def _mk_skill(root: pathlib.Path, name: str, created: float | None = None):
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    md = d / "SKILL.md"
    md.write_text(f"---\nname: {name}\ndescription: d\n---\nbody\n",
                  encoding="utf-8")
    if created is not None:
        import os
        os.utime(md, (created, created))
    return d


def test_record_and_read_roundtrip(skills):
    record_event(skills, "loaded", "alpha", ts=100.0)
    record_event(skills, "loaded", "alpha", ts=120.0, source="load_skill")
    record_event(skills, "evolved", "beta", ts=110.0)
    rows = read_events(skills)
    assert [r["event"] for r in rows] == ["loaded", "loaded", "evolved"]
    assert rows[1]["source"] == "load_skill"


def test_read_tolerates_corruption(skills):
    record_event(skills, "loaded", "alpha", ts=1.0)
    p = ledger_path(skills)
    with open(p, "a", encoding="utf-8") as f:
        f.write("{not json}\n\n")
    rows = read_events(skills)
    assert len(rows) == 1 and rows[0]["skill"] == "alpha"


def test_list_skills_excludes_archived_and_plain_dirs(skills):
    _mk_skill(skills, "alpha")
    _mk_skill(skills, "_archived")
    (skills / "no-md").mkdir()
    names = [s["name"] for s in list_skills(skills)]
    assert names == ["alpha"]


def test_ledger_report_counts_and_last_used(skills):
    _mk_skill(skills, "alpha")
    _mk_skill(skills, "beta")
    record_event(skills, "loaded", "alpha", ts=100.0)
    record_event(skills, "loaded", "alpha", ts=300.0)
    record_event(skills, "evolved", "alpha", ts=90.0)
    rep = ledger_report(skills, now=500.0)
    assert rep["skills_total"] == 2
    assert rep["loads_total"] == 2
    assert rep["evolved_events"] == 1
    by = {r["name"]: r for r in rep["skills"]}
    assert by["alpha"]["loads"] == 2 and by["alpha"]["last_used_ts"] == 300.0
    assert by["beta"]["never_used"] is True


def test_unused_candidates_semantics(skills):
    now = 10_000_000.0
    day = 86400.0
    _mk_skill(skills, "old-never", created=now - 100 * day)
    _mk_skill(skills, "old-used", created=now - 100 * day)
    _mk_skill(skills, "fresh-never", created=now - 1 * day)
    record_event(skills, "loaded", "old-used", ts=now - 5 * day)
    assert unused_candidates(skills, days=30, now=now) == ["old-never"]
    # 最近使用 → 不候选
    record_event(skills, "loaded", "old-never", ts=now - 1 * day)
    assert unused_candidates(skills, days=30, now=now) == []


def test_archive_skill_moves_not_deletes(skills, tmp_path):
    _mk_skill(skills, "alpha")
    rec = archive_skill(skills, "alpha")
    assert rec["archived"] is True, rec   # 失败携带 reason（归档竞态诊断：not-found/exists/error）
    assert not (skills / "alpha").exists()
    assert (tmp_path / "state" / "skills" / "archive" / "alpha" / "SKILL.md").exists()
    assert archive_skill(skills, "alpha") == {"archived": False,
                                                "reason": "not-found"}
    assert archive_skill(skills, "missing")["archived"] is False


def test_load_skill_records_ledger(skills):
    """load_skill 成功 → 台账记 loaded（C2 接线）。"""
    from wuxing.skills import SkillRegistry, install_skill
    from wuxing.tools.skill_tool import LoadSkillTool

    install_skill(user_dir=skills, name="demo", description="d",
                  sk_md="---\nname: demo\ndescription: d\n---\n正文\n")
    reg = SkillRegistry(user_dir=skills)
    tool = LoadSkillTool(reg)
    r = tool.execute(skill_name="demo")
    assert r.status == "ok", r.error
    rows = read_events(skills)
    assert any(e["event"] == "loaded" and e["skill"] == "demo" for e in rows)


def test_archive_skill_retries_transient_oserror(skills, monkeypatch):
    """Windows 目录 rename 瞬时占用（WinError 5）→ 有界重试。

    实证：E2-2 全量 ci_check 跑中稳定复现一次（AV/索引器扫描新建 SKILL.md
    导致 rename 瞬时拒绝）——重试后成功，不返回 error。
    """
    _mk_skill(skills, "alpha")
    real = pathlib.Path.rename
    calls = {"n": 0}

    def flaky(self, target):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError(13, "access denied")
        return real(self, target)

    monkeypatch.setattr(pathlib.Path, "rename", flaky)
    rec = archive_skill(skills, "alpha")
    assert rec["archived"] is True, rec
    assert calls["n"] == 2
