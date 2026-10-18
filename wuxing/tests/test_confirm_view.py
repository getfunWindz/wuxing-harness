"""view/kind 契约兼容性（重大优化清单 #2 · A′）。"""


def test_event_defaults_keep_old_construction():
    from wuxing.events import UnitNeedsAnswer, UnitNeedsConfirm
    e = UnitNeedsConfirm("U-1", "plan")            # 旧调用形态
    assert e.view == {}
    a = UnitNeedsAnswer("U-1", "plan", "q-1")
    assert a.kind == ""


def test_dto_shape():
    from wuxing.shell.web.contracts import ConfirmDto, QuestionListDto
    d = ConfirmDto(unit_id="U-1", domain_id="plan", reason="r")
    assert d.view == {}
    q = QuestionListDto(unit_id="U-1", domain_id="plan",
                        question_id="q-1", questions=[])
    assert q.kind == ""


def test_run_task_emits_confirm_view(tmp_path):
    """真流程（阈值 1.0）→ UnitNeedsConfirm.view 四要素齐全 + 位置/触发。"""
    from wuxing.config import EngineConfig
    from wuxing.engine import Engine
    eng = Engine(cfg=EngineConfig(confirm_threshold=1.0), workdir=tmp_path,
                 auto_confirm=False)
    events: list = []
    res = eng.run_task("写一段问候文本", on_event=events.append)
    assert res.status == "pending"
    confirms = [e for e in events if type(e).__name__ == "UnitNeedsConfirm"]
    assert confirms, "必须发出确认事件"
    v = confirms[0].view
    for key in ("title", "object", "allow_effect", "deny_effect",
                "action_hint", "trigger", "position"):
        assert str(v.get(key, "")).strip(), f"缺字段 {key}"
    assert v["trigger"].startswith("为什么问你")
    assert v["position"].startswith("任务位置")   # 共 N 步，第 i 步


def test_resume_reemit_carries_view(tmp_path):
    """W5.1 恢复态补发（达重试上限、未重调度）→ view/trigger=recovered。"""
    import pathlib

    from wuxing.engine import Engine
    from wuxing.protocols import UnitResult
    from wuxing.state import TaskState, save_state
    save_state(TaskState(
        task_text="任务",
        fragments=[{"fragment_id": "F-1", "domain": "plan", "deps": [],
                    "attempts": 2}],   # >= fragment_max_attempts(2) → 不重调度
        units=[UnitResult(unit_id="F-1", domain_id="plan",
                          status="needs_confirm")],
        status="pending"), pathlib.Path(tmp_path) / "task_state.json")
    eng = Engine(workdir=pathlib.Path(tmp_path), auto_confirm=False)
    events: list = []
    eng.resume_task(on_event=events.append)
    confirms = [e for e in events if type(e).__name__ == "UnitNeedsConfirm"]
    assert confirms, "未重调度的挂起单元必须补发（W5.1）"
    v = confirms[0].view
    assert v["trigger"].startswith("为什么问你")
    assert v["allow_effect"] and v["deny_effect"]
