"""TDD：技能自动创建（经验沉淀——失败案例→技能草稿→用户确认落盘）。

企业级「Skills 自我进化」第三环（马士兵 14P）：自动创建。
第一版机制裁决：确定性模板沉淀（失败归因+域最佳实践），不依赖 LLM 生成；
落盘前需用户确认（人工介入哲学——与安装路径一致）。
"""
import pathlib
import tempfile

from wuxing.protocols import UnitResult
from wuxing.skill_factory import draft_to_dir, find_failed_domains, suggest_skill
from wuxing.skills import SkillRegistry


def _unit(domain, status="failed", error="guard: budget/rounds exhausted"):
    return UnitResult(unit_id=f"U-{domain}-x", domain_id=domain, status=status,
                      error=error)


def test_find_failed_domains_threshold():
    """同域失败 ≥2 → 建议沉淀；不足 2 不提示。"""
    units = [_unit("execute"), _unit("execute"), _unit("plan")]
    assert find_failed_domains(units, threshold=2) == ["execute"]
    assert find_failed_domains([_unit("execute")], threshold=2) == []


def test_suggest_skill_template():
    """草稿：name/description/level=fragment/正文含失败归因与实践建议。"""
    draft = suggest_skill("execute", ["guard: budget exhausted", "tool: bash 超时"])
    assert draft.name == "execute-failure-playbook"
    assert draft.level == "fragment"
    assert "execute" in draft.description and "实践" in draft.description
    assert "budget" in draft.body and "超时" in draft.body


def test_draft_to_dir_visible_in_registry():
    """落盘用户级 → 注册表立即可见（沉淀闭环）。"""
    user = pathlib.Path(tempfile.mkdtemp())
    draft = suggest_skill("verify", ["contract: 缺少结论标记"])
    target = draft_to_dir(user, draft)
    assert (target / "SKILL.md").exists()
    reg = SkillRegistry(user_dir=user, project_dir=pathlib.Path(tempfile.mkdtemp()))
    idx = reg.index()
    assert draft.name in idx, f"落盘后必须立即可见：{list(idx.keys())}"
    assert idx[draft.name]["level"] == "fragment"
