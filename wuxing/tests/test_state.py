import pathlib
import tempfile

from wuxing.protocols import Artifact, UnitResult
from wuxing.state import TaskState, load_state, save_state


def _make_state():
    return TaskState(
        task_text="写一篇请假邮件",
        fragments=[{"fragment_id": "F-1", "domain": "plan", "deps": []}],
        units=[UnitResult(unit_id="F-1", domain_id="plan", status="ok",
                          artifacts=[Artifact(path="F-1-plan.md", kind="plan")])],
        artifacts=[Artifact(path="F-1-plan.md", kind="plan")],
        status="done")

def test_save_load_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        p = pathlib.Path(tmp) / "task_state.json"
        st = _make_state()
        save_state(st, p)
        loaded = load_state(p)
        assert loaded.task_text == "写一篇请假邮件"
        assert loaded.fragments[0]["fragment_id"] == "F-1"
        assert loaded.units[0].status == "ok"
        assert loaded.artifacts[0].path == "F-1-plan.md"

def test_load_missing_raises():
    try:
        load_state(pathlib.Path("/nonexistent/task_state.json"))
        assert False
    except FileNotFoundError:
        # 期望 FileNotFoundError：不抛则上行 assert False 失败
        pass

def test_state_roundtrip_json_serializable():
    with tempfile.TemporaryDirectory() as tmp:
        p = pathlib.Path(tmp) / "s.json"
        st = _make_state()
        save_state(st, p)
        import json
        json.loads(p.read_text(encoding="utf-8"))  # 必须纯 JSON
