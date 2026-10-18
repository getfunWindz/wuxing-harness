"""E2-1：技能格式契约与调用策略（B5 双开关 + 非法 fail-closed）。

设计权威：`docs/WUXING_技能专项设计_2026-10-03.md` §2（格式契约）/ §3（可见性模型）。
"""
import pathlib

from wuxing.skills import SkillRegistry


def _mk(root: pathlib.Path, name: str, meta: dict, body: str = "## 用法\n正文"):
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    fm = "\n".join(f"{k}: {v}" for k, v in meta.items())
    (d / "SKILL.md").write_text(f"---\n{fm}\n---\n{body}", encoding="utf-8")
    return d


def test_policy_defaults_true(tmp_path):
    _mk(tmp_path, "demo", {"name": "demo", "description": "d"})
    info = SkillRegistry(user_dir=tmp_path).index()["demo"]
    assert info["model_invocable"] is True and info["user_invocable"] is True
    assert info["policy_error"] == ""


def test_policy_explicit_false(tmp_path):
    _mk(tmp_path, "user-only", {"name": "user-only", "description": "d",
                                "model_invocable": "false"})
    info = SkillRegistry(user_dir=tmp_path).index()["user-only"]
    assert info["model_invocable"] is False and info["user_invocable"] is True


def test_policy_invalid_fail_closed(tmp_path):
    _mk(tmp_path, "bad-policy", {"name": "bad-policy", "description": "d",
                                 "model_invocable": "yes"})
    info = SkillRegistry(user_dir=tmp_path).index()["bad-policy"]
    assert info["model_invocable"] is False and info["user_invocable"] is False
    assert "model_invocable" in info["policy_error"]


def test_invalid_name_skipped(tmp_path):
    _mk(tmp_path, "Bad Name", {"name": "Bad Name", "description": "d"})
    _mk(tmp_path, "good-name", {"name": "good-name", "description": "d"})
    idx = SkillRegistry(user_dir=tmp_path).index()
    assert "Bad Name" not in idx and "good-name" in idx


def test_missing_description_skipped(tmp_path):
    _mk(tmp_path, "no-desc", {"name": "no-desc", "level": "fragment"})
    assert "no-desc" not in SkillRegistry(user_dir=tmp_path).index()


def test_invalid_level_falls_back_fragment(tmp_path):
    _mk(tmp_path, "odd-level", {"name": "odd-level", "description": "d",
                                "level": "global"})
    assert SkillRegistry(user_dir=tmp_path).index()["odd-level"]["level"] == "fragment"


def test_install_rejects_invalid(tmp_path):
    import pytest

    from wuxing.skills import install_skill
    with pytest.raises(ValueError):
        install_skill(tmp_path, "BadName", "d",
                      "---\nname: BadName\ndescription: d\n---\nx")
    with pytest.raises(ValueError):
        install_skill(tmp_path, "ok-name", "d", "无 frontmatter")


# ---------- T2：可见性/可调用性三面落地 ----------


def test_index_msg_hides_model_hidden(tmp_path):
    from wuxing.prompt_builder import build_skill_index_msg
    _mk(tmp_path, "auto-ok", {"name": "auto-ok", "description": "自动可用"})
    _mk(tmp_path, "user-only", {"name": "user-only", "description": "仅用户",
                                "model_invocable": "false"})
    msg = build_skill_index_msg(SkillRegistry(user_dir=tmp_path))
    assert "auto-ok" in msg["content"] and "user-only" not in msg["content"]


def test_index_msg_empty_when_all_hidden(tmp_path):
    from wuxing.prompt_builder import build_skill_index_msg
    _mk(tmp_path, "u1", {"name": "u1", "description": "d",
                         "model_invocable": "false"})
    assert build_skill_index_msg(SkillRegistry(user_dir=tmp_path)) is None


def test_index_reflects_catalog_change(tmp_path):
    """digest 语义锚定（设计 §3.4）：目录变更 → 重建可见；停用 → 隐藏。"""
    from wuxing.prompt_builder import build_skill_index_msg
    _mk(tmp_path, "first", {"name": "first", "description": "d"})
    reg = SkillRegistry(user_dir=tmp_path)
    assert "first" in build_skill_index_msg(reg)["content"]
    _mk(tmp_path, "second", {"name": "second", "description": "d2"})
    assert "second" in build_skill_index_msg(reg)["content"]
    msg = build_skill_index_msg(reg, disabled=("first",))
    assert "first" not in msg["content"] and "second" in msg["content"]


def test_load_skill_refuses_model_hidden(tmp_path):
    from wuxing.tools.skill_tool import LoadSkillTool
    _mk(tmp_path, "u1", {"name": "u1", "description": "d",
                         "model_invocable": "false"})
    r = LoadSkillTool(SkillRegistry(user_dir=tmp_path)).execute(skill_name="u1")
    assert r.status == "error" and "model_invocable" in r.error


def test_engine_list_skills_exposes_policy(tmp_path):
    from wuxing.config import EngineConfig
    from wuxing.engine import Engine
    _mk(tmp_path / ".skills", "user-only",
        {"name": "user-only", "description": "d", "model_invocable": "false"})
    eng = Engine(cfg=EngineConfig(llm="mock"), workdir=tmp_path)
    rows = {s["name"]: s for s in eng.list_skills()}
    row = rows["user-only"]
    assert row["model_invocable"] is False and row["user_invocable"] is True


def test_distill_to_load_chain(tmp_path):
    """自沉淀链路（验收项）：沉淀 → 注册表可见 → 索引包含 → load_skill 可加载。"""
    import json

    from wuxing.prompt_builder import build_skill_index_msg
    from wuxing.protocols import UnitResult
    from wuxing.skill_evolution import review_and_distill
    from wuxing.tools.skill_tool import LoadSkillTool

    class _Llm:
        def name(self):
            return "t"

        def chat(self, messages, tools=None):
            return json.dumps({"efficient": True, "reason": "r", "skill": {
                "name": "chain-demo", "description": "链路验证",
                "body": "## 用法\n步骤。"}})

    u = UnitResult(unit_id="F-1", domain_id="execute", status="ok")
    u.artifacts = []
    res = review_and_distill("任务", [u], "done", _Llm(), skills_dir=tmp_path)
    assert res["installed"] is True
    reg = SkillRegistry(user_dir=tmp_path)
    assert "chain-demo" in reg.index()
    assert "chain-demo" in build_skill_index_msg(reg)["content"]
    assert LoadSkillTool(reg).execute(skill_name="chain-demo").status == "ok"
