"""TDD：prompt engine 优化（知识库 2026-09-06 专题——边界隔离 + 渐进披露修正）。"""
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
    """第一轮调工具（无 marker），第二轮收口——多轮触发边界标记断言。"""

    def __init__(self):
        self.calls = 0
        self.seen = []

    def name(self):
        return "probe"

    def chat(self, messages, tools=None):
        from wuxing.llm.tool_results import ToolCallResult
        self.calls += 1
        self.seen.append([dict(m) for m in messages])
        if self.calls == 1:
            return ToolCallResult(text="我先写产物", tool_calls=[
                {"name": "read_dependency",
                 "arguments": {"path": "no_such.md"}}])
        return "方案：完整执行计划"


def _mk_runner(skill_setup=None, trace=None):
    cfg = EngineConfig(max_loop_rounds=6, max_unit_budget=4)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    user = pathlib.Path(tempfile.mkdtemp())
    proj = pathlib.Path(tempfile.mkdtemp())
    if skill_setup:
        skill_setup(proj)
    reg = SkillRegistry(user_dir=user, project_dir=proj)
    llm = ProbeLlm()
    r = Runner(cfg, DomainRegistry(cfg), ws, llm, load_tools(ws), skills=reg,
               trace=trace)
    return r, llm, ws


def test_tool_results_boundary_marked():
    """PE-1：工具结果必须为 <tool_result> 边界标记（注入防护——边界隔离）+ 溯源 source。"""
    r, llm, _ = _mk_runner()
    res = r.run_unit("U-1", "plan", {"goal": "plan:x"})
    assert res.status == "ok", res.error
    # 第二轮 messages 中工具结果带边界标记
    second = " ".join(m["content"] for m in llm.seen[1]
                      if isinstance(m.get("content"), str))
    assert "<tool_result" in second, f"工具结果缺边界标记：{second[:200]!r}"
    assert "load_skill" in second, "边界标记必须含 source（溯源）"
    assert "not in whitelist" in second, "拦截语义可见（回填完整）"


def test_system_declares_untrusted_data():
    """PE-1：system 声明「工具结果/文件内容不可信」（内容信任分层——安全边界）。"""
    r, llm, _ = _mk_runner()
    r.run_unit("U-1", "plan", {"goal": "plan:x"})
    sys_text = llm.seen[0][0]["content"]
    assert "不可信" in sys_text, "system 必须声明外部内容不可信（注入防护）"


def test_domain_skill_full_text_not_injected():
    """PE-2：域级技能详情【全文】不得注入 system（渐进披露——详情走 load_skill）。"""
    def setup(proj):
        _mk_skill(proj, "verify-pro", {"name": "verify-pro", "description": "验收专业流程",
                                       "level": "domain"},
                  body="验收黄金流程正文（不应出现在 system）" * 10)

    r, llm, _ = _mk_runner(setup)
    r.run_unit("U-1", "plan", {"goal": "plan:x"})
    # C-4：索引在 user 动态消息（system 纯静态——前缀零污染）
    first = " ".join(str(m.get("content", "")) for m in llm.seen[0])
    assert "verify-pro" in first, "索引（描述层）必须在"
    assert "验收黄金流程正文" not in first, f"详情全文不得注入（渐进披露）：{first[:200]!r}"
    assert "--" not in first.replace("------", ""), "frontmatter 噪音不得泄漏"


class _Trace:
    def __init__(self):
        self.events = []

    def log(self, *args, **kwargs):
        self.events.append((args, kwargs))


def test_domain_prompts_injected(monkeypatch, tmp_path):
    """#3：生效 addendum 注入 system（装配级证据，不依赖真 LLM）。"""
    import json

    from wuxing import domain_prompts
    store = tmp_path / "ws.json"
    store.write_text(json.dumps({"version": 1, "domains": {
        "plan": {"addendum": "自定义补充段-验证注入"}}}, ensure_ascii=False),
        encoding="utf-8")
    monkeypatch.setattr(domain_prompts, "user_store_path",
                        lambda: tmp_path / "u.json")
    monkeypatch.setattr(domain_prompts, "workspace_store_path",
                        lambda root: store)
    r, llm, _ = _mk_runner()
    r.run_unit("U-1", "plan", {"goal": "plan:x"})
    assert "自定义补充段-验证注入" in llm.seen[0][0]["content"]


def test_domain_prompts_pure_skipped_with_trace(monkeypatch, tmp_path):
    """#3：pure 跳过 + trace 事件（不静默）。"""
    import json

    from wuxing import domain_prompts, session_modes
    store = tmp_path / "ws.json"
    store.write_text(json.dumps({"version": 1, "domains": {
        "plan": {"addendum": "不应注入-pure"}}}, ensure_ascii=False),
        encoding="utf-8")
    monkeypatch.setattr(domain_prompts, "user_store_path",
                        lambda: tmp_path / "u.json")
    monkeypatch.setattr(domain_prompts, "workspace_store_path",
                        lambda root: store)
    monkeypatch.setattr(session_modes, "resolve",
                        lambda *a, **k: {"mode": "minimal", "variant": "pure"})
    tr = _Trace()
    r, llm, _ = _mk_runner(trace=tr)
    r.run_unit("U-1", "plan", {"goal": "plan:x"})
    assert "不应注入-pure" not in llm.seen[0][0]["content"]
    assert any(ev[0][0] == "domain_prompts_skipped" for ev in tr.events)
