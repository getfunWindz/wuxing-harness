"""G8-M3：run 作用域任务状态（隔离 + 兼容回退 + 消费面）。"""
from wuxing.config import EngineConfig
from wuxing.engine import Engine
from wuxing.state import latest_run_id, latest_state_path, run_state_path


def test_state_path_helpers(tmp_path):
    assert run_state_path(tmp_path, "r1") == (tmp_path / ".wuxing" / "runs"
                                              / "r1" / "task_state.json")
    assert latest_run_id(tmp_path) is None
    assert latest_state_path(tmp_path) == tmp_path / "task_state.json"
    p = run_state_path(tmp_path, "r1")
    p.parent.mkdir(parents=True)
    p.write_text("{}", encoding="utf-8")
    assert latest_run_id(tmp_path) == "r1"
    assert latest_state_path(tmp_path) == p


def test_engine_run_id_writes_run_scoped_state(tmp_path):
    eng = Engine(cfg=EngineConfig(use_real_shape=False), workdir=tmp_path,
                 run_id="r1")
    assert eng._state_path == (tmp_path / ".wuxing" / "runs" / "r1"
                               / "task_state.json")
    res = eng.run_task("写一篇请假邮件")
    assert res.status == "done"
    assert eng._state_path.is_file()
    assert not (tmp_path / "task_state.json").exists()
    eng2 = Engine(cfg=EngineConfig(use_real_shape=False), workdir=tmp_path)
    assert eng2._state_path == tmp_path / "task_state.json"


def test_session_tree_reads_latest_run_state(tmp_path):
    from wuxing.session_tree import build_task_tree
    Engine(cfg=EngineConfig(use_real_shape=False), workdir=tmp_path,
           run_id="r1").run_task("写一篇请假邮件")
    assert build_task_tree(tmp_path) is not None


def test_manager_pending_resume_reads_latest_run_state(tmp_path):
    from wuxing.protocols import UnitResult
    from wuxing.shell.web.manager import EngineManager
    from wuxing.state import TaskState, save_state
    p = run_state_path(tmp_path, "r9")
    p.parent.mkdir(parents=True)
    save_state(TaskState(task_text="待确认任务", fragments=[],
                         units=[UnitResult(unit_id="u1", domain_id="execute",
                                           status="needs_confirm")],
                         artifacts=[], status="pending"), p)
    mgr = EngineManager()
    ws = mgr.open_workspace(str(tmp_path))
    pend = mgr._pending_resume(ws)
    assert pend is not None
    assert pend["task_text"] == "待确认任务"


def test_abandon_workspace_renames_latest_run_state(tmp_path):
    from wuxing.shell.web.manager import EngineManager
    p = run_state_path(tmp_path, "r1")
    p.parent.mkdir(parents=True)
    p.write_text("{}", encoding="utf-8")
    mgr = EngineManager()
    ws = mgr.open_workspace(str(tmp_path))
    out = mgr.abandon_workspace(ws["id"])
    assert out["abandoned"] is True
    assert not p.exists()
    assert any(f.name.startswith("task_state.abandoned-")
               for f in p.parent.iterdir())
