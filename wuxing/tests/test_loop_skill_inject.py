"""TDD：Skill 体系 T2——渐进披露双轨（域主动详情 + 碎片被动 load_skill）。"""
import pathlib
import tempfile

from wuxing.config import EngineConfig
from wuxing.registry import DomainRegistry
from wuxing.runner import Runner
from wuxing.skills import SkillRegistry
from wuxing.tools.loader import load_tools
from wuxing.workspace import Workspace


def _mk_skill(root, name, meta, body="知识正文"):
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    fm = "\n".join(f"{k}: {v}" for k, v in meta.items())
    (d / "SKILL.md").write_text(f"---\n{fm}\n---\n{body}", encoding="utf-8")


class ProbeLlm:
    def __init__(self):
        self.seen = []
        self.calls = 0

    def name(self):
        return "probe"

    def chat(self, messages, tools=None):
        self.calls += 1
        self.seen.append([dict(m) for m in messages])
        return "方案：完整执行计划"


def _mk_runner_with_skills(skill_setup):
    cfg = EngineConfig(max_loop_rounds=6, max_unit_budget=4)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    user = pathlib.Path(tempfile.mkdtemp())
    proj = pathlib.Path(tempfile.mkdtemp())
    skill_setup(user, proj)
    reg = SkillRegistry(user_dir=user, project_dir=proj)
    llm = ProbeLlm()
    r = Runner(cfg, DomainRegistry(cfg), ws, llm, load_tools(ws, skills=reg), skills=reg)
    return r, llm


def test_domain_skill_detail_injected_into_system():
    """level=domain：索引标注（域级）+ 详情走 load_skill（渐进披露修正 2026-09-06）。"""
    def setup(user, proj):
        _mk_skill(proj, "verify-pro", {"name": "verify-pro", "description": "验收专业流程",
                                       "level": "domain"},
                  body="验收黄金流程：先读产物再下结论，必须引用文件行号")

    r, llm = _mk_runner_with_skills(setup)
    res = r.run_unit("U-1", "plan", {"goal": "plan:x"})
    assert res.status == "ok", res.error
    # C-4：索引在 user 动态消息（system 纯静态——前缀零污染）
    first = " ".join(str(m.get("content", "")) for m in llm.seen[0])
    assert "verify-pro" in first and "（域级）" in first, "索引标注域级"
    assert "验收黄金流程" not in first, "详情不注入（渐进披露——load_skill 按需）"


def test_fragment_skill_index_only():
    """level=fragment：system 只含索引行（name: desc），不含正文（被动——按需 load）。"""
    def setup(user, proj):
        _mk_skill(proj, "git-tips", {"name": "git-tips", "description": "git 常用流程"},
                  body="git 保留字知识正文不应该出现在索引")

    r, llm = _mk_runner_with_skills(setup)
    r.run_unit("U-1", "plan", {"goal": "plan:x"})
    first = " ".join(str(m.get("content", "")) for m in llm.seen[0])
    assert "git-tips: git 常用流程" in first, "索引行必须存在"
    assert "git 保留字知识正文" not in first, "碎片级详情不得全量注入（渐进披露）"


def test_load_skill_tool_retrieves_detail():
    """load_skill（碎片被动）：调用后详情进入下一轮上下文。"""
    def setup(user, proj):
        _mk_skill(proj, "git-tips", {"name": "git-tips", "description": "git 常用流程"},
                  body="## 流程\n先 git status 再 commit")

    from wuxing.llm.tool_results import ToolCallResult

    class LoaderLlm(ProbeLlm):
        def chat(self, messages, tools=None):
            self.calls += 1
            self.seen.append([dict(m) for m in messages])
            if self.calls == 1:
                return ToolCallResult(text="我先加载技能", tool_calls=[
                    {"name": "load_skill",
                     "arguments": {"skill_name": "git-tips"}}])
            return "方案：完整执行计划"

    cfg = EngineConfig(max_loop_rounds=6, max_unit_budget=4)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    user = pathlib.Path(tempfile.mkdtemp())
    proj = pathlib.Path(tempfile.mkdtemp())
    setup(user, proj)
    reg = SkillRegistry(user_dir=user, project_dir=proj)
    llm = LoaderLlm()
    r = Runner(cfg, DomainRegistry(cfg), ws, llm, load_tools(ws, skills=reg), skills=reg)
    res = r.run_unit("U-1", "plan", {"goal": "plan:x"})
    assert res.status == "ok", res.error
    second = " ".join(m["content"] for m in llm.seen[1]
                      if isinstance(m.get("content"), str))
    assert "先 git status 再 commit" in second, \
        f"load_skill 详情必须进入下一轮上下文：{second[:200]!r}"
