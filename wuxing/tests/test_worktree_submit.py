"""E3-1/R5（T4）：隔离 run 提交与路由（非 git 拒绝/端到端/取消/恢复/共存）。

计划：docs/plans/2026-10-03-wuxing-worktree-isolation.md（T4；W1/W3/W6）。
纪律：非 git 工作区 loud 拒绝（不静默降级共享）；账本留主、交付物落 worktree；
终态后 worktree 保留至用户 Apply/丢弃（W2）。
"""
import pathlib
import subprocess
import threading
import time
import typing

import pytest

from wuxing import worktrees
from wuxing.shell.web.manager import EngineManager


def _init_repo(root):
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "t@t"],
                   check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "t"],
                   check=True)
    (root / "a.txt").write_text("hello", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "a.txt"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "init"],
                   check=True)


class _Res:
    def __init__(self):
        self.status = "done"
        self.report = "完成"
        self.artifacts = []
        self.metrics = {}


class _WtEngine:
    """慢引擎（gate 控制）：记录 workdir/state_root（验证隔离装配与路由）。"""
    gate = threading.Event()
    instances: typing.ClassVar[list] = []

    def __init__(self, workdir, auto_confirm=False, run_id=None,
                 preset_session=None, state_root=None):
        self.workdir = pathlib.Path(workdir)
        self.state_root = pathlib.Path(state_root) if state_root else None
        self.run_id = run_id
        self.cancelled = False
        type(self).instances.append(self)

    def start_session(self, conversation_path=None):
        from wuxing.conversation import ConversationState
        from wuxing.session_api import ConversationSession
        return ConversationSession(self, ConversationState(conversation_path))

    def run_task(self, text, on_event=None, references=None, conversation=None,
                 overrides=None):
        type(self).gate.wait(10)
        return _Res()

    def resume_task(self, on_event=None):
        return _Res()

    def confirm_units(self, pairs, reason="", on_event=None):
        return _Res()

    def cancel_task(self):
        self.cancelled = True
        return True


@pytest.fixture(autouse=True)
def _reset_gate():
    _WtEngine.gate = threading.Event()
    _WtEngine.instances = []
    yield
    _WtEngine.gate.set()


def _wait(mgr, run_id, timeout=120.0):
    assert mgr._runs[run_id].done.wait(timeout)


def test_submit_isolated_non_git_rejected(tmp_path):
    """非 git 工作区显式隔离 → loud 拒绝（不静默降级共享）。"""
    mgr = EngineManager()
    ws = mgr.open_workspace(str(tmp_path))["id"]   # tmp_path 非 git
    with pytest.raises(ValueError, match="not a git repository"):
        mgr.submit(ws, "写一篇请假邮件", isolate_run=True)
    assert not mgr._runs                    # 无半启动 run
    assert not mgr._active.get(ws)


def test_submit_isolated_end_to_end(tmp_path):
    """隔离 run 端到端（真实 Engine + mock LLM）：账本留主、交付物落 worktree。"""
    ws_dir = tmp_path / "ws"
    ws_dir.mkdir()
    _init_repo(ws_dir)
    mgr = EngineManager(max_concurrent=4, max_parallel_runs_per_ws=3)
    ws = mgr.open_workspace(str(ws_dir), auto_confirm=True)["id"]
    run_id = mgr.submit(ws, "写一篇请假邮件", isolate_run=True)
    rec = mgr._runs[run_id]
    assert rec.isolated is True
    assert rec.worktree_path
    wt = pathlib.Path(rec.worktree_path)
    assert wt.is_dir()
    assert wt.is_relative_to(ws_dir / ".wuxing" / "worktrees")
    assert worktrees.run_worktree(ws_dir, run_id) == wt   # 恢复绑定标记
    _wait(mgr, run_id)
    assert rec.status == "done"
    # 账本留主工作区
    assert (ws_dir / ".wuxing" / "runs" / run_id
            / "task_state.json").is_file()
    assert not (wt / ".wuxing" / "runs").exists()
    # 交付物落 worktree
    assert (wt / "mock-plan.md").is_file()
    assert not (ws_dir / "mock-plan.md").exists()
    # W2：终态后保留（等用户 Apply/丢弃）
    assert wt.is_dir()


def test_isolated_engine_wiring_and_cancel(tmp_path):
    """隔离装配（workdir=worktree、state_root=主）+ 取消按 run 路由。"""
    ws_dir = tmp_path / "ws"
    ws_dir.mkdir()
    _init_repo(ws_dir)
    mgr = EngineManager(engine_factory=_WtEngine, max_concurrent=8,
                        max_parallel_runs_per_ws=3)
    ws = mgr.open_workspace(str(ws_dir))["id"]
    run_id = mgr.submit(ws, "任务", isolate_run=True)
    rec = mgr._runs[run_id]
    wt = pathlib.Path(rec.worktree_path)
    for _ in range(200):
        if _WtEngine.instances:
            break
        time.sleep(0.05)
    assert _WtEngine.instances, "隔离引擎未构造"
    eng = _WtEngine.instances[-1]
    assert eng.workdir == wt
    assert eng.state_root == ws_dir
    assert eng.run_id == run_id
    mgr.cancel(run_id)
    assert eng.cancelled is True
    _WtEngine.gate.set()
    _wait(mgr, run_id)


def test_shared_submit_unaffected(tmp_path):
    """默认（共享）提交不建 worktree（零行为）。"""
    ws_dir = tmp_path / "ws"
    ws_dir.mkdir()
    _init_repo(ws_dir)
    mgr = EngineManager(max_concurrent=4, max_parallel_runs_per_ws=3)
    ws = mgr.open_workspace(str(ws_dir), auto_confirm=True)["id"]
    run_id = mgr.submit(ws, "写一篇请假邮件")
    rec = mgr._runs[run_id]
    assert rec.isolated is False and rec.worktree_path == ""
    _wait(mgr, run_id)
    assert not (ws_dir / ".wuxing" / "worktrees").exists()
    assert (ws_dir / "mock-plan.md").is_file()   # 直接落主工作区


def test_recovery_engine_routes_to_worktree(tmp_path):
    """重启后恢复路由：绑定标记 → 引擎 workdir=worktree、state_root=主。"""
    ws_dir = tmp_path / "ws"
    ws_dir.mkdir()
    _init_repo(ws_dir)
    mgr = EngineManager(max_concurrent=4, max_parallel_runs_per_ws=3)
    ws = mgr.open_workspace(str(ws_dir), auto_confirm=True)["id"]
    run_id = mgr.submit(ws, "写一篇请假邮件", isolate_run=True)
    rec = mgr._runs[run_id]
    wt = pathlib.Path(rec.worktree_path)
    _wait(mgr, run_id)
    # 模拟重启：新 manager 实例（同工作区）→ 恢复引擎按标记路由
    mgr2 = EngineManager(max_concurrent=4, max_parallel_runs_per_ws=3)
    ws2 = mgr2.open_workspace(str(ws_dir), auto_confirm=True)["id"]
    eng = mgr2._recovery_engine(ws2)
    assert pathlib.Path(eng.workdir) == wt
    assert pathlib.Path(eng.state_root) == ws_dir


def test_isolated_and_shared_coexist(tmp_path):
    """隔离 run 与共享 run 并存（准入 cap 不变；worktree 只归隔离 run）。"""
    ws_dir = tmp_path / "ws"
    ws_dir.mkdir()
    _init_repo(ws_dir)
    mgr = EngineManager(engine_factory=_WtEngine, max_concurrent=8,
                        max_parallel_runs_per_ws=3)
    ws = mgr.open_workspace(str(ws_dir))["id"]
    r1 = mgr.submit(ws, "隔离任务", session="conversation-a.jsonl",
                    isolate_run=True)
    r2 = mgr.submit(ws, "共享任务", session="conversation-b.jsonl")
    assert mgr._runs[r1].worktree_path
    assert mgr._runs[r2].worktree_path == ""
    assert len(mgr._active[ws]) == 2
    _WtEngine.gate.set()
    _wait(mgr, r1)
    _wait(mgr, r2)
    by_run = {e.run_id: e for e in _WtEngine.instances}
    assert by_run[r1].workdir == pathlib.Path(mgr._runs[r1].worktree_path)
    assert by_run[r2].workdir == ws_dir
    assert by_run[r2].state_root is None   # 共享 run 不传 state_root


# ---------------- T5：Review / Apply / Discard（manager 面） ----------------

def test_worktree_review_apply_discard(tmp_path):
    """Review（文件清单+diff）→ Apply（主检出生效、worktree 保留）→ Discard（移除）。"""
    from wuxing.shell.web.manager import NotFoundError
    ws_dir = tmp_path / "ws"
    ws_dir.mkdir()
    _init_repo(ws_dir)
    mgr = EngineManager(max_concurrent=4, max_parallel_runs_per_ws=3)
    ws = mgr.open_workspace(str(ws_dir), auto_confirm=True)["id"]
    run_id = mgr.submit(ws, "写一篇请假邮件", isolate_run=True)
    rec = mgr._runs[run_id]
    wt = pathlib.Path(rec.worktree_path)
    _wait(mgr, run_id)
    # Review：变更清单 + diff（不含 .wuxing 内部面）
    rv = mgr.worktree_review(run_id)
    assert rv["path"] == rec.worktree_path
    paths = [f["path"] for f in rv["files"]]
    assert "mock-plan.md" in paths
    assert "mock-plan.md" in rv["diff"]
    assert not any(p.startswith(".wuxing") for p in paths)
    # Apply：主检出生效；worktree 保留（用户仍可丢弃）
    out = mgr.worktree_apply(run_id)
    assert out["ok"] is True and out["files"] >= 1
    assert (ws_dir / "mock-plan.md").is_file()
    assert (wt / "mock-plan.md").is_file()
    # Discard：worktree 移除；主检出成果保留
    mgr.worktree_discard(run_id)
    assert not wt.exists()
    assert (ws_dir / "mock-plan.md").is_file()
    with pytest.raises(NotFoundError):
        mgr.worktree_review(run_id)


def test_worktree_actions_reject_shared_run(tmp_path):
    """非隔离 run → NotFoundError（无 worktree 可 review/apply/discard）。"""
    from wuxing.shell.web.manager import NotFoundError
    ws_dir = tmp_path / "ws"
    ws_dir.mkdir()
    _init_repo(ws_dir)
    mgr = EngineManager(max_concurrent=4, max_parallel_runs_per_ws=3)
    ws = mgr.open_workspace(str(ws_dir), auto_confirm=True)["id"]
    run_id = mgr.submit(ws, "写一篇请假邮件")
    _wait(mgr, run_id)
    with pytest.raises(NotFoundError):
        mgr.worktree_review(run_id)
    with pytest.raises(NotFoundError):
        mgr.worktree_apply(run_id)
    with pytest.raises(NotFoundError):
        mgr.worktree_discard(run_id)
