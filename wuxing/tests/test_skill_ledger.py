"""C2（第二轮计划 §2 · 评估 P1）：技能自进化收益台账。

事件侧车 `.usage.jsonl`（loaded/evolved）→ 机械报表（触发/复用/闲置）→
淘汰建议（长期零复用；归档动作显式调用，不自动删除）。
"""
import pathlib

from wuxing.skill_ledger import (
    archive_skill,
    ledger_report,
    list_skills,
    read_events,
    record_event,
    unused_candidates,
)


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


def test_record_and_read_roundtrip(tmp_path):
    record_event(tmp_path, "loaded", "alpha", ts=100.0)
    record_event(tmp_path, "loaded", "alpha", ts=120.0, source="load_skill")
    record_event(tmp_path, "evolved", "beta", ts=110.0)
    rows = read_events(tmp_path)
    assert [r["event"] for r in rows] == ["loaded", "loaded", "evolved"]
    assert rows[1]["source"] == "load_skill"


def test_read_tolerates_corruption(tmp_path):
    record_event(tmp_path, "loaded", "alpha", ts=1.0)
    p = tmp_path / ".usage.jsonl"
    with open(p, "a", encoding="utf-8") as f:
        f.write("{not json}\n\n")
    rows = read_events(tmp_path)
    assert len(rows) == 1 and rows[0]["skill"] == "alpha"


def test_list_skills_excludes_archived_and_plain_dirs(tmp_path):
    _mk_skill(tmp_path, "alpha")
    _mk_skill(tmp_path, "_archived")
    (tmp_path / "no-md").mkdir()
    names = [s["name"] for s in list_skills(tmp_path)]
    assert names == ["alpha"]


def test_ledger_report_counts_and_last_used(tmp_path):
    _mk_skill(tmp_path, "alpha")
    _mk_skill(tmp_path, "beta")
    record_event(tmp_path, "loaded", "alpha", ts=100.0)
    record_event(tmp_path, "loaded", "alpha", ts=300.0)
    record_event(tmp_path, "evolved", "alpha", ts=90.0)
    rep = ledger_report(tmp_path, now=500.0)
    assert rep["skills_total"] == 2
    assert rep["loads_total"] == 2
    assert rep["evolved_events"] == 1
    by = {r["name"]: r for r in rep["skills"]}
    assert by["alpha"]["loads"] == 2 and by["alpha"]["last_used_ts"] == 300.0
    assert by["beta"]["never_used"] is True


def test_unused_candidates_semantics(tmp_path):
    now = 10_000_000.0
    day = 86400.0
    _mk_skill(tmp_path, "old-never", created=now - 100 * day)
    _mk_skill(tmp_path, "old-used", created=now - 100 * day)
    _mk_skill(tmp_path, "fresh-never", created=now - 1 * day)
    record_event(tmp_path, "loaded", "old-used", ts=now - 5 * day)
    assert unused_candidates(tmp_path, days=30, now=now) == ["old-never"]
    # 最近使用 → 不候选
    record_event(tmp_path, "loaded", "old-never", ts=now - 1 * day)
    assert unused_candidates(tmp_path, days=30, now=now) == []


def test_archive_skill_moves_not_deletes(tmp_path):
    _mk_skill(tmp_path, "alpha")
    rec = archive_skill(tmp_path, "alpha")
    assert rec["archived"] is True, rec   # 失败携带 reason（归档竞态诊断：not-found/exists/error）
    assert not (tmp_path / "alpha").exists()
    assert (tmp_path / "_archived" / "alpha" / "SKILL.md").exists()
    assert archive_skill(tmp_path, "alpha") == {"archived": False,
                                                "reason": "not-found"}
    assert archive_skill(tmp_path, "missing")["archived"] is False


def test_load_skill_records_ledger(tmp_path):
    """load_skill 成功 → 台账记 loaded（C2 接线）。"""
    from wuxing.skills import SkillRegistry, install_skill
    from wuxing.tools.skill_tool import LoadSkillTool

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    install_skill(user_dir=skills_dir, name="demo", description="d",
                  sk_md="---\nname: demo\ndescription: d\n---\n正文\n")
    reg = SkillRegistry(user_dir=skills_dir)
    tool = LoadSkillTool(reg)
    r = tool.execute(skill_name="demo")
    assert r.status == "ok", r.error
    rows = read_events(skills_dir)
    assert any(e["event"] == "loaded" and e["skill"] == "demo" for e in rows)


def test_archive_skill_retries_transient_oserror(tmp_path, monkeypatch):
    """Windows 目录 rename 瞬时占用（WinError 5）→ 有界重试。

    实证：E2-2 全量 ci_check 跑中稳定复现一次（AV/索引器扫描新建 SKILL.md
    导致 rename 瞬时拒绝）——重试后成功，不返回 error。
    """
    _mk_skill(tmp_path, "alpha")
    real = pathlib.Path.rename
    calls = {"n": 0}

    def flaky(self, target):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError(13, "access denied")
        return real(self, target)

    monkeypatch.setattr(pathlib.Path, "rename", flaky)
    rec = archive_skill(tmp_path, "alpha")
    assert rec["archived"] is True, rec
    assert calls["n"] == 2
