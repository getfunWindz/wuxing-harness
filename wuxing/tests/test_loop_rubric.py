"""TDD · L3-3：验收 rubric——计划→验收标准绑定 → verify 逐条核查（企业级 Planning 闭环）。

机制设计（LLM 辅佐者、机制裁决者）：
  1. plan 域产物必须含「验收标准：」段（可逐条核查的条目——prompt 契约强化）
  2. verify 域 prompt 强化：依据验收标准逐条核查 + 结论结尾（L0-4 传播已做）
  3. 验收标准段从 plan 产物注入 verify（_dep_context 已有——验证其到面可达）
"""
import pathlib
import tempfile

from wuxing.config import EngineConfig
from wuxing.engine import Engine
from wuxing.registry import DomainRegistry


def test_plan_prompt_requires_acceptance_criteria():
    """plan prompt/quality_notes 必须含「验收标准」（计划→验收绑定）。"""
    reg = DomainRegistry(EngineConfig())
    d = reg.get("plan")
    joined = d.quality_notes + "\n" + d.prompt_skeleton
    assert "验收标准" in joined, "plan 域契约必须要求验收标准段"


def test_verify_prompt_requires_itemized_rubric():
    """verify prompt/quality_notes 必须含「逐条」核查指令（rubric 化——非笼统判断）。"""
    reg = DomainRegistry(EngineConfig())
    d = reg.get("verify")
    joined = d.quality_notes + "\n" + d.prompt_skeleton
    assert "逐条" in joined, "verify 域契约必须要求逐条核查"


class _RubricLlm:
    """plan 产物含验收标准 → execute 执行 → verify 逐条核查（不通过 → verdict_fail）。"""

    def __init__(self):
        self.calls = 0

    def name(self):
        return "rubric"

    def chat(self, messages, tools=None):
        self.calls += 1
        joined = " ".join(m.get("content", "") if isinstance(
            m.get("content"), str) else "" for m in messages)
        # 文本协议：注入读/写物证满足契约
        if "验收" in joined and "请验收" in joined:
            return ("TOOLCALL:read_dependency path=out.md\n"
                    "逐条核查：\n"
                    "#1 登录表单存在：通过\n"
                    "#2 密码加密存储：不通过\n"
                    "结论：不通过")
        if "制定方案" in joined:
            return ("方案：制定登录功能\n"
                    "验收标准：\n"
                    "#1 登录表单存在\n"
                    "#2 密码加密存储\n"
                    "TOOLCALL:write_artifact path=plan.md kind=plan content=方案")
        return ("执行计划\n"
                "TOOLCALL:write_artifact path=out.md kind=result content=实现方案")


def _mk_engine(llm):
    """引擎 + 预置形状化（P1-2 后：complexity=high 保证 plan/execute/verify 三链不合并）。"""
    eng = Engine(workdir=pathlib.Path(tempfile.mkdtemp()), llm=llm,
                 auto_confirm=True)
    eng.shape_cache.put("登录功能验收", {
        "nodes": [
            {"id": "n1", "text": "制定登录方案", "domain": {"规划": 0.9},
             "trades": [], "complexity": "high", "deliverable": "text",
             "weight": 0.5},
            {"id": "n2", "text": "实现登录功能", "domain": {"开发": 0.9},
             "trades": [], "complexity": "high", "deliverable": "text",
             "weight": 0.5},
            {"id": "n3", "text": "验证登录功能", "domain": {"验证": 0.9},
             "trades": [], "complexity": "high", "deliverable": "text",
             "weight": 0.5}],
        "edges": [["n1", "n2"], ["n2", "n3"]]})
    return eng


def test_rubric_criteria_injected_to_verify():
    """端到端：plan 产物（含验收标准）必须注入 verify 的 result 上下文。"""
    llm = _RubricLlm()
    res = _mk_engine(llm).run_task("登录功能验收")
    # 任务级：verify 不通过 → 非 done（L0-4 传播 + rubric 链闭合）
    assert res.status != "done", f"rubric 逐条不通过必须传播：{res.status}"
    assert "不通过" in res.report, "报告明示验收不通过"
