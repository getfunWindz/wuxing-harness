"""TDD：技能启停（M7 挂账 #5 · A1——用户裁决 2026-09-20）。

- 默认全部启用；停用状态持久化（sidecar：~/.wuxing/skills-disabled.json，测试隔离）
- 停用后：list_skills 标记 enabled=False；load_skill 工具拒绝；技能索引消息不列出
- 内置技能不可停用；未知/非法技能名报错
"""
import pytest

from wuxing.config import EngineConfig
from wuxing.engine import Engine


def _mk(tmp_path, monkeypatch):
    import wuxing.skill_state as st
    monkeypatch.setattr(st, "state_path", lambda: tmp_path / "skills-disabled.json")
    wd = tmp_path / "wd"
    sdir = wd / ".skills" / "my-skill"
    sdir.mkdir(parents=True)
    (sdir / "SKILL.md").write_text(
        "---\nname: my-skill\ndescription: 测试技能\n---\n\n正文\n",
        encoding="utf-8")
    return Engine(cfg=EngineConfig(llm="mock"), workdir=wd), wd


def test_list_skills_default_enabled(tmp_path, monkeypatch):
    eng, _wd = _mk(tmp_path, monkeypatch)
    names = {s["name"]: s for s in eng.list_skills()}
    assert names["my-skill"]["enabled"] is True


def test_set_skill_enabled_marks_and_persists(tmp_path, monkeypatch):
    eng, wd = _mk(tmp_path, monkeypatch)
    assert eng.set_skill_enabled("my-skill", False)["enabled"] is False
    marked = {s["name"]: s for s in eng.list_skills()}
    assert marked["my-skill"]["enabled"] is False
    # 持久化：新实例（同 sidecar）仍为停用
    eng2 = Engine(cfg=EngineConfig(llm="mock"), workdir=wd)
    marked2 = {s["name"]: s for s in eng2.list_skills()}
    assert marked2["my-skill"]["enabled"] is False
    # 重新启用
    assert eng.set_skill_enabled("my-skill", True)["enabled"] is True
    marked3 = {s["name"]: s for s in eng.list_skills()}
    assert marked3["my-skill"]["enabled"] is True


def test_load_skill_refuses_disabled(tmp_path, monkeypatch):
    eng, _wd = _mk(tmp_path, monkeypatch)
    from wuxing.tools.skill_tool import LoadSkillTool
    tool = LoadSkillTool(eng.skills)
    eng.set_skill_enabled("my-skill", False)
    res = tool.execute(skill_name="my-skill")
    assert res.status == "error"
    assert "停用" in (res.error or "")
    eng.set_skill_enabled("my-skill", True)
    assert tool.execute(skill_name="my-skill").status == "ok"


def test_set_skill_enabled_rejections(tmp_path, monkeypatch):
    eng, _wd = _mk(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        eng.set_skill_enabled("find-skill", False)      # 内置只读
    with pytest.raises(ValueError):
        eng.set_skill_enabled("no-such-skill", False)   # 未知
    with pytest.raises(ValueError):
        eng.set_skill_enabled("bad/name", False)        # 路径遍历


def test_prompt_skill_index_excludes_disabled(tmp_path, monkeypatch):
    eng, _wd = _mk(tmp_path, monkeypatch)
    from wuxing.prompt_builder import build_skill_index_msg
    eng.set_skill_enabled("my-skill", False)
    msg = build_skill_index_msg(eng.skills)
    assert msg is None or "my-skill" not in msg["content"]
