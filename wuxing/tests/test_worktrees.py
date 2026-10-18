"""E3-1/R5：worktree 生命周期（创建/列表/移除/非 git loud 拒绝）+ setup 声明。

计划：docs/plans/2026-10-03-wuxing-worktree-isolation.md（T1/T3）。
纪律：显式档——非 git 工作区 loud 拒绝（绝不静默降级共享执行）；失败透出 git stderr。
"""
import json
import subprocess

import pytest

from wuxing.worktrees import (
    WorktreeError,
    create,
    is_git_repo,
    list_worktrees,
    load_setup,
    remove,
    run_setup,
    setup_commands,
    worktree_path,
)


def _init_repo(root):
    """git init + 本地身份 + 首个提交（worktree add 需要 HEAD 存在）。"""
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "t@t"],
                   check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "t"],
                   check=True)
    (root / "a.txt").write_text("hello", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "a.txt"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "init"],
                   check=True)
    return root


def test_non_git_rejected_loud(tmp_path):
    """非 git 工作区 → isolate 不可用（错误可见，不静默降级）。"""
    assert is_git_repo(tmp_path) is False
    with pytest.raises(WorktreeError, match="not a git repository"):
        create(tmp_path, "run_1")


def test_create_list_remove(tmp_path):
    """git init 后：create(run_id) → 路径存在且独立检出；list 含之；remove 后消失。"""
    _init_repo(tmp_path)
    assert is_git_repo(tmp_path) is True
    path = create(tmp_path, "run_1")
    assert path == worktree_path(tmp_path, "run_1")
    assert path.is_dir() and (path / "a.txt").is_file()
    assert path in list_worktrees(tmp_path)
    remove(tmp_path, "run_1")
    assert not path.exists()
    assert path not in list_worktrees(tmp_path)


def test_remove_keeps_main_clean(tmp_path):
    """worktree 内改动不触碰主检出；remove 后主检出文件不变。"""
    _init_repo(tmp_path)
    path = create(tmp_path, "run_1")
    (path / "a.txt").write_text("changed", encoding="utf-8")
    (path / "new.txt").write_text("new", encoding="utf-8")
    remove(tmp_path, "run_1")
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "hello"
    assert not (tmp_path / "new.txt").exists()


def test_create_twice_loud(tmp_path):
    """重复 create 同 run → loud 拒绝（不静默复用）。"""
    _init_repo(tmp_path)
    create(tmp_path, "run_1")
    with pytest.raises(WorktreeError, match="already exists"):
        create(tmp_path, "run_1")


def test_run_id_traversal_rejected(tmp_path):
    """run_id 进路径前校验（防目录穿越/非法字符）。"""
    _init_repo(tmp_path)
    with pytest.raises(WorktreeError, match="run_id"):
        worktree_path(tmp_path, "../evil")
    with pytest.raises(WorktreeError, match="run_id"):
        create(tmp_path, "a/b")


# ---------------- T3：setup 声明（CU9） ----------------

def _write_decl(root, payload):
    (root / "wuxing.worktree.json").write_text(
        json.dumps(payload), encoding="utf-8")


def test_setup_no_declaration_noop(tmp_path):
    """无声明零行为（不建文件/不执行命令）。"""
    assert load_setup(tmp_path) == {}
    out = run_setup(tmp_path, tmp_path / "wt")
    assert out["ok"] is True
    assert out["commands"] == 0 and out["copied"] == 0


def test_setup_commands_ordered_in_worktree(tmp_path):
    """命令按声明顺序执行，cwd=worktree（不污染主检出）。"""
    main = tmp_path / "main"
    wt = tmp_path / "wt"
    main.mkdir()
    wt.mkdir()
    _write_decl(main, {"setup": ["echo first> order.txt",
                                 "echo second>> order.txt"]})
    out = run_setup(main, wt)
    assert out["ok"] is True and out["commands"] == 2
    lines = [x.strip() for x in
             (wt / "order.txt").read_text(encoding="utf-8").splitlines()
             if x.strip()]
    assert lines == ["first", "second"]
    assert not (main / "order.txt").exists()


def test_setup_env_copy_from_main(tmp_path):
    """env_copy：从主检出复制到 worktree（含新建目录）。"""
    main = tmp_path / "main"
    wt = tmp_path / "wt"
    main.mkdir()
    wt.mkdir()
    (main / ".env").write_text("SECRET=1", encoding="utf-8")
    (main / "cfg").mkdir()
    (main / "cfg" / "app.env").write_text("A=2", encoding="utf-8")
    _write_decl(main, {"env_copy": [".env", "cfg/app.env"]})
    out = run_setup(main, wt)
    assert out["ok"] is True and out["copied"] == 2
    assert (wt / ".env").read_text(encoding="utf-8") == "SECRET=1"
    assert (wt / "cfg" / "app.env").read_text(encoding="utf-8") == "A=2"


def test_setup_env_missing_visible(tmp_path):
    """env_copy 源缺失 → 失败可见（不静默继续）。"""
    main = tmp_path / "main"
    wt = tmp_path / "wt"
    main.mkdir()
    wt.mkdir()
    _write_decl(main, {"env_copy": [".env"]})
    out = run_setup(main, wt)
    assert out["ok"] is False
    assert ".env" in out["error"]


def test_setup_command_failure_visible_fail_fast(tmp_path):
    """命令失败 → 失败可见（退出码+命令透出）且后续命令不执行。"""
    main = tmp_path / "main"
    wt = tmp_path / "wt"
    main.mkdir()
    wt.mkdir()
    _write_decl(main, {"setup": ["exit 3", "echo never> never.txt"]})
    out = run_setup(main, wt)
    assert out["ok"] is False
    assert "exit 3" in out["error"]
    assert not (wt / "never.txt").exists()


def test_setup_platform_specific(tmp_path):
    """setup + setup_unix/setup_windows 按平台合并。"""
    decl = {"setup": ["a"], "setup_unix": ["u"], "setup_windows": ["w"]}
    assert setup_commands(decl, platform="nt") == ["a", "w"]
    assert setup_commands(decl, platform="posix") == ["a", "u"]


def test_setup_malformed_visible(tmp_path):
    """声明非法 JSON → loud 拒绝（不静默当无声明）。"""
    (tmp_path / "wuxing.worktree.json").write_text("{oops", encoding="utf-8")
    with pytest.raises(WorktreeError, match="setup"):
        load_setup(tmp_path)


def test_setup_timeout_visible(tmp_path, monkeypatch):
    """超时 → 失败可见（映射为 WorktreeError，不悬挂）。"""
    main = tmp_path / "main"
    wt = tmp_path / "wt"
    main.mkdir()
    wt.mkdir()
    _write_decl(main, {"setup": ["sleep forever"]})
    import wuxing.worktrees as _wt

    def _boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="sleep forever", timeout=0.1)

    monkeypatch.setattr(_wt.subprocess, "run", _boom)
    out = run_setup(main, wt, timeout_s=0.1)
    assert out["ok"] is False
    assert "timeout" in out["error"].lower() or "超时" in out["error"]


def test_setup_alt_location(tmp_path):
    """.wuxing/worktree.json 回退路径可用（根文件优先）。"""
    alt = tmp_path / ".wuxing"
    alt.mkdir()
    (alt / "worktree.json").write_text(
        json.dumps({"setup": ["echo x"]}), encoding="utf-8")
    assert load_setup(tmp_path).get("setup") == ["echo x"]
    (tmp_path / "wuxing.worktree.json").write_text(
        json.dumps({"setup": ["echo root"]}), encoding="utf-8")
    assert load_setup(tmp_path).get("setup") == ["echo root"]
