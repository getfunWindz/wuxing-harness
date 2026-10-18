"""E3-1/R5：state_root 分离——账本留主工作区；文件操作落 worktree。

计划：docs/plans/2026-10-03-wuxing-worktree-isolation.md（T2；W3）。
边界：run 账本（runs/trace/provenance/sessions/manifest/缓存）写 state_root；
交付物文件与命令执行落 workdir；缺省 state_root=None → 行为与现状完全一致。
"""
from wuxing.engine import Engine


def test_state_root_separation(tmp_path):
    """workdir=worktree、state_root=主工作区 → run 状态/账本落主工作区；
    文件操作（write_artifact）落 worktree。"""
    main = tmp_path / "main"
    wt = tmp_path / "worktree"
    main.mkdir()
    wt.mkdir()
    eng = Engine(workdir=wt, state_root=main, run_id="run_t1",
                 auto_confirm=True)
    res = eng.run_task("写一篇请假邮件")
    assert res.status == "done"
    # 运行状态 → 主工作区（worktree 无 runs）
    assert (main / ".wuxing" / "runs" / "run_t1"
            / "task_state.json").is_file()
    assert not (wt / ".wuxing" / "runs").exists()
    # 观测层（trace/provenance）→ 主工作区
    assert (main / ".wuxing" / "trace.jsonl").is_file()
    assert (main / ".wuxing" / "provenance.jsonl").is_file()
    # 会话存档 → 主工作区
    assert (main / ".wuxing" / "sessions").is_dir()
    # 产物登记（manifest）→ 主工作区
    assert (main / "manifest.json").is_file()
    assert not (wt / "manifest.json").exists()
    # 文件操作 → worktree（mock 产物 + 契约报告归档仍在 worktree，模型可读回）
    assert (wt / "mock-plan.md").is_file()
    assert list((wt / ".wuxing" / "reports").glob("*-result.md"))
    assert not (main / "mock-plan.md").exists()
    assert not (main / ".wuxing" / "reports").exists()


def test_legacy_default_unchanged(tmp_path):
    """缺省 state_root=None → 行为与现状完全一致（全部落 workdir）。"""
    eng = Engine(workdir=tmp_path, run_id="run_t1", auto_confirm=True)
    assert eng.state_root == tmp_path
    res = eng.run_task("写一篇请假邮件")
    assert res.status == "done"
    assert (tmp_path / ".wuxing" / "runs" / "run_t1"
            / "task_state.json").is_file()
    assert (tmp_path / ".wuxing" / "trace.jsonl").is_file()
    assert (tmp_path / "manifest.json").is_file()


def test_workspace_root_contains_wuxing_component(tmp_path):
    """T4 实证：root 路径含 `.wuxing` 组件（worktree 布局）→ 普通文件不得被
    内部面守卫误杀；`.wuxing/` 子路径仍隐藏。"""
    import pytest

    from wuxing.workspace import Workspace
    root = tmp_path / ".wuxing" / "worktrees" / "run_1"
    root.mkdir(parents=True)
    (root / "a.txt").write_text("hi", encoding="utf-8")
    ws = Workspace(root)
    assert ws.read("a.txt") == "hi"
    with pytest.raises(ValueError, match="internal"):
        ws._safe_path(".wuxing/trace.jsonl")
