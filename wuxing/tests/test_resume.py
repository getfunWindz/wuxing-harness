import pathlib
import tempfile

from wuxing.engine import Engine
from wuxing.state import load_state


def test_engine_saves_state_after_run():
    eng = Engine(workdir=pathlib.Path(tempfile.mkdtemp()), auto_confirm=True)
    eng.run_task("写一篇请假邮件")
    state = load_state(eng.workdir / "task_state.json")
    assert state.task_text == "写一篇请假邮件"
    assert state.status == "done"

def test_engine_resume_skips_done_units():
    eng = Engine(workdir=pathlib.Path(tempfile.mkdtemp()), auto_confirm=True)
    eng.run_task("写一篇请假邮件")
    # 同工作区新引擎 → resume
    eng2 = Engine(workdir=eng.workdir)
    r2 = eng2.resume_task()
    assert r2.status in ("done", "partial")
    assert len(r2.artifacts) >= 1

def test_engine_resume_without_state_raises():
    eng = Engine(workdir=pathlib.Path(tempfile.mkdtemp()), auto_confirm=True)
    try:
        eng.resume_task()
        assert False
    except FileNotFoundError:
        # 期望 FileNotFoundError（无可恢复状态）：不抛则上方 assert False
        pass

def test_engine_resume_pending_units_seeded_deps():
    # 关键：pending 碎片的 deps 引用已完成碎片 → resume 不因 deps 死锁
    from wuxing.protocols import UnitResult
    from wuxing.state import TaskState, save_state
    tmp = tempfile.mkdtemp()
    # 构建状态：F-1(plan) 已完成，F-2(execute) pending 依赖 F-1
    save_state(TaskState(
        task_text="写一篇请假邮件",
        fragments=[
            {"fragment_id": "F-1", "domain": "plan", "deps": []},
            {"fragment_id": "F-2", "domain": "execute", "deps": ["F-1"]},
        ],
        units=[UnitResult(unit_id="F-1", domain_id="plan", status="ok")],
        status="running"), pathlib.Path(tmp) / "task_state.json")
    eng = Engine(workdir=pathlib.Path(tmp))
    r = eng.resume_task()
    assert r.status in ("done", "partial")
    unit_map = {u.unit_id: u for u in r.units}
    assert "F-2" in unit_map
    assert unit_map["F-2"].status == "ok"  # 关键：F-2 真实执行成功（非死锁 failed）


def _mk_capped_pending_state(tmp, attempts):
    """构建状态：F-1 ok；F-2(verify) needs_confirm（fragment attempts 指定）。"""
    from wuxing.protocols import UnitResult
    from wuxing.state import TaskState, save_state
    save_state(TaskState(
        task_text="验任务",
        fragments=[
            {"fragment_id": "F-1", "domain": "execute", "deps": [],
             "text": "执行"},
            {"fragment_id": "F-2", "domain": "verify", "deps": ["F-1"],
             "text": "验收", "attempts": attempts},
        ],
        units=[UnitResult(unit_id="F-1", domain_id="execute", status="ok"),
               UnitResult(unit_id="F-2", domain_id="verify",
                          status="needs_confirm")],
        status="pending"), pathlib.Path(tmp) / "task_state.json")


def test_resume_reemits_pending_for_unscheduled_unit():
    """W5.1：恢复时未重新调度但仍挂起的单元必须补发 UnitNeedsConfirm。

    现场（A 复跑）：F-T4-v attempts 触顶不再调度 → 无挂起事件 →
    resume_workspace 新 run 的 pending 列表为空 → 界面不可见/不可确认。
    """
    tmp = tempfile.mkdtemp()
    _mk_capped_pending_state(tmp, attempts=2)   # 默认 cap=2 → 触顶不调度
    eng = Engine(workdir=pathlib.Path(tmp), auto_confirm=False)
    events = []
    res = eng.resume_task(on_event=events.append)
    assert res.status == "pending"
    confirms = [e for e in events if type(e).__name__ == "UnitNeedsConfirm"]
    assert [e.unit_id for e in confirms] == ["F-2"]
    assert confirms[0].domain_id == "verify"
    assert confirms[0].impact.get("depends") == ["F-1"]


def test_resume_does_not_duplicate_pending_event_for_scheduled_unit():
    """W5.1：本轮已调度的挂起单元不得重复发事件（orchestrator 已发一次）。"""
    tmp = tempfile.mkdtemp()
    _mk_capped_pending_state(tmp, attempts=0)   # 未触顶 → 重新调度
    eng = Engine(workdir=pathlib.Path(tmp), auto_confirm=False)
    events = []
    res = eng.resume_task(on_event=events.append)
    assert res.status == "pending"
    confirms = [e for e in events if type(e).__name__ == "UnitNeedsConfirm"]
    assert [e.unit_id for e in confirms] == ["F-2"]


def test_resume_seeds_external_done_deps_from_tickets(tmp_path):
    """真测缺陷（P0-1 验证）：外部已完成依赖跨「确认续跑」必须继续满足。

    现场（ws-theroad2）：初始 run 为 done 票的验收碎片（F-T1-v 等）建了 seed，
    但 seed 只活在 run 内存；确认 F-T3-v 续跑后 _resume_task_impl 从 state.units
    重建 done → F-T5 的 done 票依赖（F-T1-v）消失 → `unsatisfied deps (cycle)`
    误判失败（attempts=None——实际从未运行）。
    """
    from wuxing import tickets as tk
    from wuxing.protocols import UnitResult
    from wuxing.state import TaskState, save_state
    t1 = tk.create(tmp_path, title="T1")
    t5 = tk.create(tmp_path, title="T5", deps=[t1["id"]])
    tk.update(tmp_path, t1["id"], {"status": "done"})
    tk.update(tmp_path, t5["id"], {"status": "ready"})
    save_state(TaskState(
        task_text="复跑",
        fragments=[
            {"fragment_id": "F-T3", "domain": "execute", "deps": []},
            {"fragment_id": "F-T3-v", "domain": "verify", "deps": ["F-T3"]},
            {"fragment_id": "F-T5", "domain": "execute", "ticket": "T-5",
             "deps": ["F-T1-v", "F-T3-v"]},
            {"fragment_id": "F-T5-v", "domain": "verify", "deps": ["F-T5"]},
        ],
        units=[UnitResult(unit_id="F-T3", domain_id="execute", status="ok"),
               UnitResult(unit_id="F-T3-v", domain_id="verify", status="ok")],
        status="pending"), pathlib.Path(tmp_path) / "task_state.json")
    eng = Engine(workdir=pathlib.Path(tmp_path), auto_confirm=False)
    captured = {}

    def fake_run(pending, task_text, **kw):
        captured["seed"] = kw.get("seed_done") or {}
        return [UnitResult(unit_id=f["fragment_id"], domain_id=f["domain"],
                           status="ok") for f in pending]

    eng.orchestrator.run = fake_run
    res = eng.resume_task()
    assert captured["seed"].get("F-T1-v") is not None, \
        "done 票的验收碎片必须作为外部已完成依赖 seed（防 unsatisfied deps）"
    assert captured["seed"]["F-T1-v"].status == "ok"
    assert res.status == "done", res.report[-400:]
