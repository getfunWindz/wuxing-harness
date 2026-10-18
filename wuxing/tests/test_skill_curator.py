"""E2-1：curator 生命周期（确定性转换；绝不删除；可恢复）。

设计权威：`docs/WUXING_技能专项设计_2026-10-03.md` §4。
"""
import pathlib

from wuxing import skill_ledger, skill_state
from wuxing.skill_curator import (
    apply_transitions,
    restore_skill,
    skill_status,
    transitions_due,
)

DAY = 86400.0


def _mk(root: pathlib.Path, name: str, created: float):
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    md = d / "SKILL.md"
    md.write_text(f"---\nname: {name}\ndescription: d\n---\nbody\n",
                  encoding="utf-8")
    import os
    os.utime(md, (created, created))
    return d


def _iso(monkeypatch, tmp_path):
    monkeypatch.setattr(skill_state, "pinned_path",
                        lambda: tmp_path / "skills-pinned.json")


def test_transitions_thresholds(tmp_path, monkeypatch):
    _iso(monkeypatch, tmp_path)
    now = 10_000_000.0
    _mk(tmp_path / "s", "old-unused", created=now - 100 * DAY)
    _mk(tmp_path / "s", "fresh", created=now - 1 * DAY)
    _mk(tmp_path / "s", "stale-only", created=now - 16 * DAY)
    due = transitions_due(tmp_path / "s", now=now)
    assert "old-unused" in due["archive"] and "stale-only" in due["stale"]
    assert "stale-only" not in due["archive"] and "fresh" not in due["stale"]


def test_used_skill_archive_without_grace(tmp_path, monkeypatch):
    _iso(monkeypatch, tmp_path)
    now = 10_000_000.0
    _mk(tmp_path / "s", "used-long-ago", created=now - 100 * DAY)
    skill_ledger.record_event(tmp_path / "s", "loaded", "used-long-ago",
                              ts=now - 40 * DAY)
    due = transitions_due(tmp_path / "s", now=now)
    assert "used-long-ago" in due["archive"], due
    assert skill_status(tmp_path / "s", "used-long-ago", now=now) == "stale"


def test_pinned_skips_transitions(tmp_path, monkeypatch):
    _iso(monkeypatch, tmp_path)
    now = 10_000_000.0
    _mk(tmp_path / "s", "keep-me", created=now - 100 * DAY)
    skill_state.save_pinned({"keep-me"})
    due = transitions_due(tmp_path / "s", now=now)
    assert "keep-me" not in due["stale"] and "keep-me" not in due["archive"]


def test_apply_and_restore(tmp_path, monkeypatch):
    _iso(monkeypatch, tmp_path)
    now = 10_000_000.0
    _mk(tmp_path / "s", "old", created=now - 100 * DAY)
    out = apply_transitions(tmp_path / "s", now=now)
    assert out["archived"] == ["old"]
    assert (tmp_path / "state" / "s" / "archive" / "old").is_dir()
    assert skill_status(tmp_path / "s", "old", now=now) == "archived"
    assert restore_skill(tmp_path / "s", "old")["restored"] is True
    assert skill_status(tmp_path / "s", "old", now=now) == "stale"
    # 目标已存在 → 拒绝（不覆盖）
    _mk(tmp_path / "s", "dup", created=now)
    (tmp_path / "s" / "_archived" / "dup").mkdir(parents=True)
    assert restore_skill(tmp_path / "s", "dup") == {"restored": False,
                                                    "reason": "exists"}


def test_restore_missing(tmp_path, monkeypatch):
    _iso(monkeypatch, tmp_path)
    (tmp_path / "s").mkdir()
    assert restore_skill(tmp_path / "s", "nope") == {"restored": False,
                                                     "reason": "not-found"}


def test_restore_retries_transient_oserror(tmp_path, monkeypatch):
    """恢复路径同样有界重试（Windows 目录 rename 瞬时占用——同归档动机）。"""
    import pathlib
    _iso(monkeypatch, tmp_path)
    _mk(tmp_path / "s", "x", created=1000.0)
    assert skill_ledger.archive_skill(tmp_path / "s", "x")["archived"] is True
    real = pathlib.Path.rename
    calls = {"n": 0}

    def flaky(self, target):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError(13, "access denied")
        return real(self, target)

    monkeypatch.setattr(pathlib.Path, "rename", flaky)
    assert restore_skill(tmp_path / "s", "x")["restored"] is True
    assert calls["n"] == 2


# ---------- 2026-10-15：近义检测（curator 报告 + 自沉淀查重核心） ----------

def _mk_full(root: pathlib.Path, name: str, body: str, *,
             description: str = "d", created: float | None = None):
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    md = d / "SKILL.md"
    md.write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n{body}\n",
        encoding="utf-8")
    if created is not None:
        import os
        os.utime(md, (created, created))
    return d


def test_similarity_core():
    from wuxing.skill_curator import bigrams, jaccard, name_tokens, pair_similarity
    assert name_tokens("Python-TDD-Flow") == {"python", "tdd", "flow"}
    assert name_tokens("") == set()
    assert bigrams("a b") == {"ab"}          # 去全部空白
    assert bigrams("") == set()
    assert jaccard(set(), {"x"}) == 0.0 and jaccard({"x"}, {"x"}) == 1.0
    same = pair_similarity("alpha-flow", "步骤一：先写测试。",
                           "beta-flow", "步骤一：先写测试。")
    assert same["body_j"] == 1.0 and same["match"] is True
    assert "body" in same["matched_by"] and "name" not in same["matched_by"]
    none = pair_similarity("alpha", "苹果香蕉", "beta", "月亮星星")
    assert none["match"] is False and none["matched_by"] == []


def test_near_duplicate_report_clusters_and_singletons(tmp_path):
    from wuxing.skill_curator import near_duplicate_report
    root = tmp_path / "s"
    body = "步骤一：先写失败测试。步骤二：最小实现。步骤三：回归。"
    _mk_full(root, "pytest-minimal-function", body)
    _mk_full(root, "pytest-minimal-smoke", body)
    _mk_full(root, "pytest-minimal-verify", body)
    _mk_full(root, "leave-request-email", "写请假邮件：抬头、事由、日期、落款。")
    rep = near_duplicate_report(root)
    assert rep["skills_total"] == 4
    assert len(rep["clusters"]) == 1
    c = rep["clusters"][0]
    assert c["members"] == ["pytest-minimal-function", "pytest-minimal-smoke",
                            "pytest-minimal-verify"]
    assert c["max_body_j"] == 1.0
    assert rep["singletons"] == ["leave-request-email"]
    assert len(rep["pairs"]) == 3


def test_report_excludes_archived_and_broken(tmp_path):
    from wuxing.skill_curator import near_duplicate_report
    root = tmp_path / "s"
    body = "步骤一：先写失败测试。步骤二：最小实现。"
    _mk_full(root, "keep-a", body)
    _mk_full(root, "keep-b", body)
    _mk_full(root / "_archived", "old-a", body)          # 归档 —— 排除
    (root / "no-md").mkdir(parents=True)                  # 无 SKILL.md —— 排除
    (root / "bad-fm").mkdir(parents=True)
    (root / "bad-fm" / "SKILL.md").write_text("无 frontmatter 正文",
                                              encoding="utf-8")
    rep = near_duplicate_report(root)
    assert rep["skills_total"] == 2
    assert rep["clusters"][0]["members"] == ["keep-a", "keep-b"]


def test_canonical_prefers_loads_then_created(tmp_path):
    from wuxing.skill_curator import near_duplicate_report
    root = tmp_path / "s"
    body = "步骤一：先写失败测试。步骤二：最小实现。"
    _mk_full(root, "aaa-flow", body, created=1_000.0)
    _mk_full(root, "bbb-flow", body, created=2_000.0)
    skill_ledger.record_event(root, "loaded", "bbb-flow", ts=3_000.0)
    c = near_duplicate_report(root)["clusters"][0]
    assert c["canonical"] == "bbb-flow" and c["canonical_loads"] == 1
    # 并列 loads=0 → 创建早者
    root2 = tmp_path / "s2"
    _mk_full(root2, "ccc-flow", body, created=1_000.0)
    _mk_full(root2, "ddd-flow", body, created=2_000.0)
    assert near_duplicate_report(root2)["clusters"][0]["canonical"] == "ccc-flow"


def test_find_near_duplicate(tmp_path):
    from wuxing.skill_curator import find_near_duplicate
    root = tmp_path / "s"
    body = "步骤一：先写失败测试。步骤二：最小实现。"
    _mk_full(root, "pytest-minimal-function", body, description="纯函数 TDD")
    hit = find_near_duplicate(root, name="pytest-minimal-smoke", body=body)
    assert hit["name"] == "pytest-minimal-function"
    assert hit["body_j"] == 1.0 and hit["description"] == "纯函数 TDD"
    assert find_near_duplicate(root, name="leave-mail",
                               body="写请假邮件：抬头、事由。") is None
    assert find_near_duplicate(tmp_path / "nope", name="x", body="y") is None


def test_near_duplicate_report_empty_dir(tmp_path):
    from wuxing.skill_curator import near_duplicate_report
    rep = near_duplicate_report(tmp_path / "none")
    assert rep["skills_total"] == 0
    assert rep["clusters"] == [] and rep["pairs"] == []
