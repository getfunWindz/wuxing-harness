"""TDD · M3-1：Skills LLM 版草稿生成——失败案例 → LLM 草稿 → frontmatter 校验 → 人工确认。

模板版（确定性——诚实标注）为基线；本层：LLM 生成草稿（case 语义提炼——
更贴近真实失败模式）+ 结构校验（frontmatter 必须可解析——不合格回退模板版）。
"""
import pathlib
import tempfile

from wuxing.skill_factory import (
    SkillDraft,
    draft_to_dir,
    llm_sketch_skill,
)


class _SketchLlm:
    """mock LLM：返回合格草稿（frontmatter 完整）。"""

    def name(self):
        return "sketch"

    def chat(self, messages, tools=None):
        return ("---\nname: execute-retry-playbook\n"
                "description: 执行域重试实践的技能\n"
                "level: fragment\n---\n"
                "## 最佳实践\n先读依赖再产出，收口优先。\n")


class _BadSketchLlm:
    """无 frontmatter 输出（不合格——回退模板版）。"""

    def name(self):
        return "bad"

    def chat(self, messages, tools=None):
        return "这是没有 frontmatter 的草稿正文"


def test_llm_draft_validated():
    """LLM 草稿：frontmatter 校验通过 → SkillDraft（name/描述抽取）。"""
    d = llm_sketch_skill(_SketchLlm(), "execute", ["预算耗尽", "工具超时"])
    assert isinstance(d, SkillDraft)
    assert d.name == "execute-retry-playbook"
    assert "最佳实践" in d.body


def test_invalid_llm_draft_falls_back():
    """LLM 草稿不合格（无 frontmatter）→ 回退模板版（机制不依赖模型自觉）。"""
    d = llm_sketch_skill(_BadSketchLlm(), "verify", ["未给结论"])
    assert d.name == "verify-failure-playbook", "回退确定性模板（诚实标注）"
    assert "检查清单" in d.body


def test_draft_install_roundtrip():
    """草稿落盘（人工确认后）→ 注册表可见（技能生态闭环）。"""
    d = SkillDraft(name="unit-test-skill", description="测试技能", body="正文")
    user_dir = pathlib.Path(tempfile.mkdtemp())
    target = draft_to_dir(user_dir, d)
    assert (target / "SKILL.md").exists()
    from wuxing.skills import SkillRegistry
    idx = SkillRegistry(user_dir=user_dir).index()
    assert "unit-test-skill" in idx
    assert idx["unit-test-skill"]["description"] == "测试技能"
