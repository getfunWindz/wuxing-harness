"""P3：sidecar 收敛到 `<skills_dir>/../state/<name>/`，并兼容旧路径。"""
from __future__ import annotations

import pathlib

from wuxing import skill_ledger, skill_state
from wuxing.skill_curator import restore_skill


def _mk_skill(root: pathlib.Path, name: str) -> pathlib.Path:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: d\n---\nbody\n",
        encoding="utf-8",
    )
    return d


def test_ledger_writes_state_dir_and_reads_legacy(tmp_path):
    skills = tmp_path / "skills"
    _mk_skill(skills, "alpha")
    (skills / ".usage.jsonl").write_text(
        '{"ts": 1, "event": "loaded", "skill": "alpha"}\n',
        encoding="utf-8",
    )
    assert skill_ledger.read_events(skills)[0]["skill"] == "alpha"

    skill_ledger.record_event(skills, "loaded", "alpha", ts=2)
    new_path = tmp_path / "state" / "skills" / "usage.jsonl"
    assert new_path.exists()
    rows = skill_ledger.read_events(skills)
    assert len(rows) == 1 and rows[0]["ts"] == 2


def test_archive_uses_state_dir_and_restores_legacy(tmp_path):
    skills = tmp_path / "skills"
    _mk_skill(skills, "alpha")
    assert skill_ledger.archive_skill(skills, "alpha")["archived"] is True
    assert (
        tmp_path / "state" / "skills" / "archive" / "alpha" / "SKILL.md"
    ).exists()
    assert restore_skill(skills, "alpha")["restored"] is True

    legacy = skills / "_archived" / "beta"
    legacy.mkdir(parents=True)
    (legacy / "SKILL.md").write_text(
        "---\nname: beta\ndescription: d\n---\nbody\n", encoding="utf-8")
    assert restore_skill(skills, "beta")["restored"] is True


def test_skill_state_new_paths_and_legacy_read(tmp_path, monkeypatch):
    monkeypatch.setattr(
        skill_state, "state_path",
        lambda: tmp_path / "state" / "skills" / "disabled.json")
    monkeypatch.setattr(
        skill_state, "pinned_path",
        lambda: tmp_path / "state" / "skills" / "pinned.json")
    monkeypatch.setattr(
        skill_state, "legacy_state_path",
        lambda: tmp_path / "skills-disabled.json")
    monkeypatch.setattr(
        skill_state, "legacy_pinned_path",
        lambda: tmp_path / "skills-pinned.json")

    (tmp_path / "skills-disabled.json").write_text(
        '{"names": ["old"]}', encoding="utf-8")
    assert skill_state.load_disabled() == {"old"}

    skill_state.save_disabled({"new"})
    assert (tmp_path / "state" / "skills" / "disabled.json").exists()
    assert skill_state.load_disabled() == {"new"}


def test_builtin_resources_path():
    import wuxing

    builtin = pathlib.Path(wuxing.__file__).parent / "resources" / "skills"
    assert (builtin / "find-skill" / "SKILL.md").exists()
