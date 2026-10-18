import pathlib
import tempfile

from wuxing.engine import Engine
from wuxing.protocols import Artifact, UnitResult
from wuxing.state import TaskState, save_state


def _mk_state_with_pending():
    tmp = tempfile.mkdtemp()
    save_state(TaskState(
        task_text="写一篇请假邮件",
        fragments=[{"fragment_id": "F-1", "domain": "plan", "deps": []}],
        units=[UnitResult(unit_id="F-1", domain_id="plan", status="needs_confirm")],
        status="running"), pathlib.Path(tmp) / "task_state.json")
    return tmp

def test_engine_confirm_unit_approve_resumes():
    tmp = _mk_state_with_pending()
    eng = Engine(workdir=pathlib.Path(tmp), auto_confirm=False)
    result = eng.confirm_unit("F-1", approve=True)
    # 确认后：该 unit 从 needs_confirm → 重新执行 → ok
    unit = next(u for u in result.units if u.unit_id == "F-1")
    assert unit.status == "ok"

def test_engine_confirm_unit_reject_marks_failed():
    tmp = _mk_state_with_pending()
    eng = Engine(workdir=pathlib.Path(tmp), auto_confirm=False)
    result = eng.confirm_unit("F-1", approve=False)
    unit = next(u for u in result.units if u.unit_id == "F-1")
    # 壳 P1 对齐项③（2026-09-13）：驳回 = rejected 终态（UI 可区分）；
    # 任务级仍为 failed；错误信息保留 "rejected" 语义
    assert unit.status == "rejected"
    assert "rejected" in unit.error
    assert result.status == "failed"

def test_engine_confirm_unit_unknown_raises():
    tmp = _mk_state_with_pending()
    eng = Engine(workdir=pathlib.Path(tmp), auto_confirm=False)
    try:
        eng.confirm_unit("NOPE", approve=True)
        assert False
    except KeyError:
        # 期望 KeyError（不抛则上方 assert False 先失败）
        pass


def _mk_state_with_deps_pending():
    """F-plan 已完成（产物 plan.md 带验收标准）+ F-v 挂起（deps=[F-plan]）。"""
    tmp = pathlib.Path(tempfile.mkdtemp())
    (tmp / "plan.md").write_text(
        "方案：1. 实现登录 2. 验证\n验收标准：登录成功", encoding="utf-8")
    save_state(TaskState(
        task_text="实现并验证登录功能",
        fragments=[
            {"fragment_id": "F-plan", "domain": "plan", "deps": [],
             "text": "制定登录方案", "deliverables": [], "granularity": 0.5},
            {"fragment_id": "F-v", "domain": "verify", "deps": ["F-plan"],
             "text": "验证登录", "deliverables": [], "granularity": 0.4}],
        units=[
            UnitResult(unit_id="F-plan", domain_id="plan", status="ok",
                       artifacts=[Artifact(path="plan.md", kind="plan",
                                           producer_unit="F-plan")]),
            UnitResult(unit_id="F-v", domain_id="verify",
                       status="needs_confirm")],
        status="running"), tmp / "task_state.json")
    return str(tmp)


def test_confirm_unit_verify_gets_dep_paths():
    """A2：确认续跑参数完整——verify 单元必须收到依赖产物**路径**（paths 非空），
    否则机制自动兜底失效 + 模型盲猜路径探索。"""
    tmp = _mk_state_with_deps_pending()

    class CaptureLlm:
        def __init__(self):
            self.usage_history = []
            self.call_count = 0
            self.prompts = []

        def name(self):
            return "capture"

        def spec(self):
            return "capture"

        def supports_native_tools(self):
            return False

        def chat(self, messages, tools=None):
            self.usage_history.append({"input": 0, "output": 0,
                                       "cache_read": 0, "cache_write": 0})
            self.prompts = list(messages)
            return "TOOLCALL:read_dependency path=plan.md\n结论：通过"

    eng = Engine(workdir=pathlib.Path(tmp), llm=CaptureLlm(),
                 auto_confirm=False)
    res = eng.confirm_unit("F-v", approve=True)
    assert res.status in ("done", "ok", "pending", "partial", "failed")  # 状态由聚合决定
    llm = eng.llm
    assert llm.prompts, "确认续跑必须实际调用 LLM"
    prompt = "\n".join(m["content"] for m in llm.prompts
                        if m.get("role") == "user")
    assert "plan.md" in prompt, \
        f"verify 确认续跑必须携带依赖产物路径：\n{prompt[:300]}"


def test_confirm_unit_execute_gets_plan():
    """A2：execute 单元确认续跑必须收到 plan 上下文（方案注入——不是重新盲探索）。"""
    tmp = _mk_state_with_deps_pending()

    class CaptureLlm:
        def __init__(self):
            self.usage_history = []
            self.call_count = 0
            self.prompts = []

        def name(self):
            return "capture2"

        def spec(self):
            return "capture2"

        def supports_native_tools(self):
            return False

        def chat(self, messages, tools=None):
            self.usage_history.append({"input": 0, "output": 0,
                                       "cache_read": 0, "cache_write": 0})
            self.prompts = list(messages)
            return ("TOOLCALL:write_artifact path=app.py kind=result "
                    "content=print(1)\n执行完成")

    eng = Engine(workdir=pathlib.Path(tmp), llm=CaptureLlm(),
                 auto_confirm=False)
    # 再造一个挂起的 execute 单元（deps=[F-plan]）
    from wuxing.state import load_state
    st = load_state(pathlib.Path(tmp) / "task_state.json")
    st.fragments.append({"fragment_id": "F-e", "domain": "execute",
                         "deps": ["F-plan"], "text": "实现登录",
                         "deliverables": [], "granularity": 0.3})
    st.units.append(UnitResult(unit_id="F-e", domain_id="execute",
                               status="needs_confirm"))
    from wuxing.state import save_state
    save_state(st, pathlib.Path(tmp) / "task_state.json")
    res = eng.confirm_unit("F-e", approve=True)
    assert res.status in ("done", "ok", "pending", "partial", "failed")
    llm = eng.llm
    prompt = "\n".join(m["content"] for m in llm.prompts
                        if m.get("role") == "user")
    assert "1. 实现登录" in prompt or "plan.md" in prompt, \
        f"execute 确认续跑须带 plan 内容/路径：\n{prompt[:300]}"


def test_confirm_unit_continues_dependents():
    """真测裁决 W3：批准挂起单元后，其下游碎片自动续跑（同 resume 机制）。"""
    tmp = pathlib.Path(tempfile.mkdtemp())
    save_state(TaskState(
        task_text="任务",
        fragments=[
            {"fragment_id": "A", "domain": "plan", "deps": []},
            {"fragment_id": "B", "domain": "execute", "deps": ["A"],
             "require_ok_deps": True},
        ],
        units=[UnitResult(unit_id="A", domain_id="plan",
                          status="needs_confirm")],
        status="pending"), tmp / "task_state.json")
    eng = Engine(workdir=tmp, auto_confirm=True)
    result = eng.confirm_unit("A", approve=True)
    ids = {u.unit_id: u.status for u in result.units}
    assert ids["A"] == "ok"
    assert ids.get("B") == "ok", "下游碎片必须在批准后自动续跑"


def test_confirm_does_not_run_other_pending_units():
    """批准 A 时不得连带执行未确认的 C（挂起等待各自的确认）。"""
    tmp = pathlib.Path(tempfile.mkdtemp())
    save_state(TaskState(
        task_text="任务",
        fragments=[
            {"fragment_id": "A", "domain": "plan", "deps": []},
            {"fragment_id": "C", "domain": "execute", "deps": []},
        ],
        units=[UnitResult(unit_id="A", domain_id="plan", status="needs_confirm"),
               UnitResult(unit_id="C", domain_id="execute",
                          status="needs_confirm")],
        status="pending"), tmp / "task_state.json")
    eng = Engine(workdir=tmp, auto_confirm=True)
    result = eng.confirm_unit("A", approve=True)
    ids = {u.unit_id: u.status for u in result.units}
    assert ids["A"] == "ok"
    assert ids.get("C") == "needs_confirm", "未确认单元不得被续跑"


def _state_with_attempts(tmp, attempts_a, extra_frags=None, units_extra=None):
    frags = [{"fragment_id": "A", "domain": "plan", "deps": [],
              "attempts": attempts_a}]
    frags += extra_frags or []
    units = [UnitResult(unit_id="A", domain_id="plan", status="failed")]
    units += units_extra or []
    save_state(TaskState(task_text="任务", fragments=frags, units=units,
                         status="failed"),
               pathlib.Path(tmp) / "task_state.json")


def test_resume_retries_below_cap():
    """W4.3：尝试次数 < 上限 → 允许重试。"""
    tmp = tempfile.mkdtemp()
    _state_with_attempts(tmp, 1)
    eng = Engine(workdir=pathlib.Path(tmp), auto_confirm=True)
    result = eng.resume_task()
    a = [u for u in result.units if u.unit_id == "A"][-1]  # resume 追加：取最新
    assert a.status == "ok", "上限内（1<2）允许重试"


def test_resume_respects_retry_cap_and_records():
    """W4.3：达上限不再重试；未尝试碎片照常调度；留痕（trace + 报告注记）。"""
    tmp = tempfile.mkdtemp()
    _state_with_attempts(
        tmp, 2,
        extra_frags=[{"fragment_id": "B", "domain": "execute", "deps": [],
                      "attempts": 0}])
    eng = Engine(workdir=pathlib.Path(tmp), auto_confirm=True)
    result = eng.resume_task()
    a = next(u for u in result.units if u.unit_id == "A")
    b = next(u for u in result.units if u.unit_id == "B")
    assert a.status == "failed", "达上限的碎片不得再调度"
    assert b.status == "ok", "未尝试碎片照常调度"
    assert "重试上限" in result.report, "报告必须留痕（回退为只调度未尝试碎片）"
    trace = pathlib.Path(tmp, ".wuxing", "trace.jsonl").read_text(encoding="utf-8")
    assert "retry_cap_exhausted" in trace


def test_attempts_persist_across_resume():
    """W4.3：attempts 计次必须随 task_state 持久化（上限裁决依赖它跨续跑累计）。"""
    import json

    tmp = tempfile.mkdtemp()
    _state_with_attempts(tmp, 0)
    eng = Engine(workdir=pathlib.Path(tmp), auto_confirm=True)
    eng.resume_task()
    frags = json.loads(pathlib.Path(tmp, "task_state.json").read_text(
        encoding="utf-8"))["fragments"]
    a = next(f for f in frags if f["fragment_id"] == "A")
    assert int(a.get("attempts") or 0) == 1, \
        f"恢复重跑后 attempts 应累计（实际 {a.get('attempts')}）"
