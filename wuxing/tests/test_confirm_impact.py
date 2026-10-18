"""TDD：确认门影响清单（M7 #7 · A2）——UnitNeedsConfirm.impact。

影响字段：tools（域工具白名单）/ deliverables（交付类型）/ depends（依赖碎片）/
summary（碎片摘要）——引擎事件与壳投影同源。
"""
from wuxing.config import EngineConfig
from wuxing.engine import Engine
from wuxing.events import UnitNeedsConfirm


def _run(tmp_path):
    events = []
    eng = Engine(cfg=EngineConfig(llm="mock", confirm_threshold=1.0),
                 workdir=tmp_path, auto_confirm=False)
    eng.run_task("写一份测试计划", on_event=events.append)
    return [e for e in events if isinstance(e, UnitNeedsConfirm)]


def test_confirm_event_carries_impact(tmp_path):
    confirms = _run(tmp_path)
    assert confirms, "confirm_threshold=1.0 应触发确认挂起"
    ev = confirms[0]
    impact = getattr(ev, "impact", None)
    assert isinstance(impact, dict) and impact, "影响清单必须携带且非空"
    assert isinstance(impact.get("tools"), list) and impact["tools"], impact
    assert impact.get("summary"), impact
    assert isinstance(impact.get("deliverables"), list)
    assert isinstance(impact.get("depends"), list)
