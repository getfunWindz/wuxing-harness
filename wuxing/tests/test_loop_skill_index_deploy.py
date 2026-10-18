"""TDD · C-4：技能索引尾部署——索引从 system 移出（system 纯静态=前缀零污染）。

B5 遗留：技能索引注入 system——技能安装/变更 → system 变化 → 服务端缓存前缀破坏。
修复：索引作为独立 user 消息（system 永不变；索引变化只在尾部动态区）。
"""
import pathlib
import tempfile

from wuxing.config import EngineConfig
from wuxing.registry import DomainRegistry
from wuxing.runner import Runner
from wuxing.skills import SkillRegistry
from wuxing.tools.loader import load_tools
from wuxing.workspace import Workspace


def test_system_never_contains_skill_index():
    """system 不含技能索引（纯静态——技能安装不影响前缀）。"""
    proj = pathlib.Path(tempfile.mkdtemp())
    (proj / "git-tips").mkdir()
    (proj / "git-tips" / "SKILL.md").write_text(
        "---\nname: git-tips\ndescription: git 常用流程\n---\n正文", encoding="utf-8")
    reg = SkillRegistry(user_dir=pathlib.Path(tempfile.mkdtemp()),
                        project_dir=proj)

    class L:
        def __init__(self): self.seen = []
        def name(self): return "l"
        def chat(self, messages, tools=None):
            self.seen.append([dict(m) for m in messages])
            return "x"
    cfg = EngineConfig(max_loop_rounds=2, max_unit_budget=2)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    llm = L()
    r = Runner(cfg, DomainRegistry(cfg), ws, llm, load_tools(ws, skills=reg),
               skills=reg)
    r.run_unit("U-1", "plan", {"goal": "g"})
    sys_text = llm.seen[0][0]["content"]
    assert "可用技能" not in sys_text and "git-tips" not in sys_text, \
        "system 必须纯静态（技能索引移出——前缀零污染）"
    # 索引在 user 动态区（独立消息）
    user_msgs = [m for m in llm.seen[0] if m.get("role") == "user"]
    assert any("git-tips" in str(m.get("content", "")) for m in user_msgs), \
        "技能索引必须在 user 消息（动态区——变更不影响前缀）"


def test_system_stable_across_skill_install():
    """技能安装前后 system 逐字节不变（前缀稳定——B5 防御）。"""
    proj = pathlib.Path(tempfile.mkdtemp())
    reg = SkillRegistry(user_dir=pathlib.Path(tempfile.mkdtemp()),
                        project_dir=proj)

    class L2:
        def __init__(self): self.seen = []
        def name(self): return "l2"
        def chat(self, messages, tools=None):
            self.seen.append([dict(m) for m in messages])
            return "x"
    cfg = EngineConfig(max_loop_rounds=2, max_unit_budget=2)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    llm = L2()
    r = Runner(cfg, DomainRegistry(cfg), ws, llm, load_tools(ws, skills=reg),
               skills=reg)
    r.run_unit("U-1", "plan", {"goal": "g"})
    before = llm.seen[0][0]["content"]
    # 安装新技能（模拟运行期变更）
    from wuxing.skills import install_skill
    install_skill(proj, "new-skill", "描述", "---\nname: new-skill\ndescription: 描述\n---\n正文")
    llm2 = L2()
    r2 = Runner(cfg, DomainRegistry(cfg), ws, llm2, load_tools(ws, skills=reg),
                skills=reg)
    r2.run_unit("U-1", "plan", {"goal": "g"})
    assert llm2.seen[0][0]["content"] == before, \
        "技能安装不得改变 system（前缀稳定——缓存不破坏）"
