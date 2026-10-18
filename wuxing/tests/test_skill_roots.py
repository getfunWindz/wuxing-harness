"""P0：`.agents/skills` 便携根只读兼容（用户 + 项目）。

扫描顺序（后者覆盖同名）：
  builtin < 用户 ~/.wuxing/skills < 用户 ~/.agents/skills
         < 项目 <ws>/.skills < 项目 <ws>/.agents/skills
显式 `user_dir`（含 None）不默认扫描 `~/.agents/skills`——保持 G4 隔离。
"""
from __future__ import annotations

import pathlib

from wuxing.config import EngineConfig
from wuxing.engine import Engine
from wuxing.skills import SkillRegistry


def _skill(root: pathlib.Path, name: str, description: str) -> None:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n正文",
        encoding="utf-8",
    )


def test_project_agents_root_wins_over_all_layers(tmp_path):
    builtin = tmp_path / "builtin"
    user = tmp_path / "user"
    user_agents = tmp_path / "user_agents"
    project = tmp_path / "project"
    project_agents = tmp_path / "project_agents"
    _skill(builtin, "demo", "builtin")
    _skill(user, "demo", "user")
    _skill(user_agents, "demo", "user_agents")
    _skill(project, "demo", "project")
    _skill(project_agents, "demo", "project_agents")

    reg = SkillRegistry(
        user_dir=user,
        user_agents_dir=user_agents,
        project_dir=project,
        project_agents_dir=project_agents,
        builtin_dir=builtin,
    )
    assert reg.index()["demo"]["description"] == "project_agents"


def test_agents_root_order_without_project_agents(tmp_path):
    user = tmp_path / "user"
    user_agents = tmp_path / "user_agents"
    project = tmp_path / "project"
    _skill(user, "demo", "user")
    _skill(user_agents, "demo", "user_agents")
    _skill(project, "demo", "project")

    reg = SkillRegistry(
        user_dir=user,
        user_agents_dir=user_agents,
        project_dir=project,
        project_agents_dir=tmp_path / "missing_project_agents",
    )
    assert reg.index()["demo"]["description"] == "project"

    reg2 = SkillRegistry(
        user_dir=user,
        user_agents_dir=user_agents,
        project_dir=tmp_path / "missing_project",
        project_agents_dir=tmp_path / "missing_project_agents",
    )
    assert reg2.index()["demo"]["description"] == "user_agents"


def test_missing_agents_roots_are_zero_behavior(tmp_path):
    user = tmp_path / "user"
    _skill(user, "only-user", "user")
    reg = SkillRegistry(
        user_dir=user,
        user_agents_dir=tmp_path / "missing_user_agents",
        project_dir=None,
        project_agents_dir=tmp_path / "missing_project_agents",
    )
    assert "only-user" in reg.index()


def test_agents_root_change_invalidates_index(tmp_path):
    user = tmp_path / "user"
    user.mkdir()
    agents = tmp_path / "agents"
    reg = SkillRegistry(
        user_dir=user,
        user_agents_dir=agents,
        project_dir=None,
        project_agents_dir=None,
    )
    assert reg.index() == {}
    _skill(agents, "late-skill", "late")
    assert "late-skill" in reg.index(), "新增 .agents 技能必须触发索引重建"


def test_explicit_user_dir_does_not_default_agents_root(tmp_path):
    reg = SkillRegistry(
        user_dir=tmp_path / "user",
        project_dir=None,
        builtin_dir=None,
    )
    assert reg.user_agents_dir is None


def test_user_dir_none_skips_agents_root(tmp_path, monkeypatch):
    monkeypatch.setattr("os.path.expanduser", lambda _: str(tmp_path))
    _skill(tmp_path / ".agents" / "skills", "should-not-load", "x")
    reg = SkillRegistry(user_dir=None, project_dir=None, builtin_dir=None)
    assert reg.user_agents_dir is None
    assert reg.index() == {}


def test_default_agents_root_uses_home(tmp_path, monkeypatch):
    monkeypatch.setattr("os.path.expanduser", lambda _: str(tmp_path))
    _skill(tmp_path / ".agents" / "skills", "home-agent", "home")
    reg = SkillRegistry()
    assert reg.user_dir == tmp_path / ".wuxing" / "skills"
    assert reg.user_agents_dir == tmp_path / ".agents" / "skills"
    assert "home-agent" in reg.index()


def test_engine_wires_project_agents_root(tmp_path):
    _skill(tmp_path / ".agents" / "skills", "proj-agent", "project agents")
    eng = Engine(cfg=EngineConfig(llm="mock"), workdir=tmp_path)
    assert eng.skills.project_agents_dir == tmp_path / ".agents" / "skills"
    assert "proj-agent" in {s["name"] for s in eng.list_skills()}


def test_engine_isolated_skips_agents_roots(tmp_path):
    _skill(tmp_path / "ws" / ".agents" / "skills", "ignored", "x")
    eng = Engine(workdir=tmp_path / "ws", isolated=True)
    assert eng.skills.user_agents_dir is None
    assert eng.skills.project_agents_dir is None
    assert eng.skills.index() == {}


def test_legacy_project_skills_warns_once(tmp_path, caplog, monkeypatch):
    """P1：项目 .skills 为 legacy——保留兼容，但每进程只告警一次。"""
    import wuxing.skills as skills_mod

    monkeypatch.setattr(skills_mod, "_LEGACY_PROJECT_WARNED", False)
    project = tmp_path / ".skills"
    _skill(project, "legacy-skill", "legacy")
    reg = SkillRegistry(
        user_dir=tmp_path / "user",
        project_dir=project,
        project_agents_dir=tmp_path / "missing_agents",
        builtin_dir=None,
    )
    with caplog.at_level("WARNING", logger="wuxing.skills"):
        assert "legacy-skill" in reg.index()
        reg.index()
    records = [r for r in caplog.records if ".skills" in r.getMessage()]
    assert len(records) == 1, caplog.text


def test_engine_project_agents_wins_over_legacy_skills(tmp_path):
    """P1：engine 同时发现 .agents/skills 与 .skills 时，canonical 覆盖 legacy。"""
    _skill(tmp_path / ".skills", "demo", "legacy")
    _skill(tmp_path / ".agents" / "skills", "demo", "canonical")
    eng = Engine(cfg=EngineConfig(llm="mock"), workdir=tmp_path)
    skills = {s["name"]: s for s in eng.list_skills()}
    assert skills["demo"]["description"] == "canonical"


def test_engine_legacy_skills_still_scanned(tmp_path):
    """P1：.agents/skills 不存在时，.skills 仍可用（兼容回退）。"""
    _skill(tmp_path / ".skills", "legacy-only", "legacy")
    eng = Engine(cfg=EngineConfig(llm="mock"), workdir=tmp_path)
    assert "legacy-only" in {s["name"] for s in eng.list_skills()}
