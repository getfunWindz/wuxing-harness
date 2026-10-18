"""G8-M3：并发不变量（设计 §5）——真实引擎实例的并行执行集成。"""
import pathlib

from wuxing.config import EngineConfig
from wuxing.shell.web.manager import EngineManager
from wuxing.state import run_state_path


def _real_factory(workdir, auto_confirm=False, run_id=None):
    from wuxing.engine import Engine
    return Engine(cfg=EngineConfig(use_real_shape=False),
                  workdir=pathlib.Path(workdir),
                  auto_confirm=bool(auto_confirm), run_id=run_id)


def test_two_parallel_real_runs_isolated_state(tmp_path):
    (tmp_path / "ws").mkdir()
    mgr = EngineManager(engine_factory=_real_factory, max_concurrent=8,
                        max_parallel_runs_per_ws=3)
    ws = mgr.open_workspace(str(tmp_path / "ws"))["id"]
    r1 = mgr.submit(ws, "写一篇请假邮件", session="conversation-a.jsonl")
    r2 = mgr.submit(ws, "写一篇会议通知", session="conversation-b.jsonl")
    assert r1 != r2
    mgr.wait(r1, timeout=60)
    mgr.wait(r2, timeout=60)
    p1 = run_state_path(tmp_path / "ws", r1)
    p2 = run_state_path(tmp_path / "ws", r2)
    assert p1.is_file() and p2.is_file()
    assert p1 != p2
    assert mgr._runs[r1].status == "done"
    assert mgr._runs[r2].status == "done"
    # 旧根级状态未被使用（新 run 一律 run 作用域）
    assert not (tmp_path / "ws" / "task_state.json").exists()
