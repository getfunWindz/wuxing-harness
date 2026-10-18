import pathlib
import tempfile

from wuxing.engine import Engine
from wuxing.events import ArtifactWritten, UnitDone, UnitStarted


def test_engine_emits_unit_events():
    eng = Engine(workdir=pathlib.Path(tempfile.mkdtemp()), auto_confirm=True)
    events = []
    eng.run_task("写一篇请假邮件", on_event=events.append)
    kinds = {type(e) for e in events}
    assert UnitStarted in kinds
    assert UnitDone in kinds

def test_engine_emits_artifact_written():
    eng = Engine(workdir=pathlib.Path(tempfile.mkdtemp()), auto_confirm=True)
    events = []
    eng.run_task("写一篇请假邮件", on_event=events.append)
    arts = [e for e in events if isinstance(e, ArtifactWritten)]
    assert len(arts) >= 1
    assert arts[0].path.endswith(".md")

def test_engine_without_on_event_still_works():
    eng = Engine(workdir=pathlib.Path(tempfile.mkdtemp()), auto_confirm=True)
    r = eng.run_task("写一篇请假邮件")
    assert r.status == "done"
