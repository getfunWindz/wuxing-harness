"""E3-1/R5：worktree 隔离运行——生命周期（创建/列表/移除/非 git loud 拒绝）。

设计：`docs/plans/2026-10-03-wuxing-worktree-isolation.md`（T1；裁定 W1/W2/W5）。
- 位置：`<workdir>/.wuxing/worktrees/<run_id>/`（`.wuxing/` 已 gitignored）。
- **显式档**：非 git 工作区 → loud 拒绝（绝不静默降级共享执行）。
- **失败 loud**：git stderr 透出（`WorktreeError`）；不自动合并、不自动清理
  （worktree 保留至用户 Apply/丢弃——W2/W5）。
"""
import json
import logging
import os
import pathlib
import re
import shutil
import subprocess

logger = logging.getLogger(__name__)

_RUN_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")


class WorktreeError(RuntimeError):
    """worktree 操作失败（loud——含 git stderr 细节）。"""


def _validate_run_id(run_id) -> str:
    """run_id 进路径前校验（防目录穿越/路径分隔符注入）。"""
    rid = str(run_id or "")
    if not rid or rid in (".", "..") or not _RUN_ID_RE.match(rid):
        raise WorktreeError(f"invalid run_id（拒绝路径字符）: {run_id!r}")
    return rid


def worktrees_dir(workdir) -> pathlib.Path:
    """worktree 根目录：`<workdir>/.wuxing/worktrees/`。"""
    return pathlib.Path(workdir) / ".wuxing" / "worktrees"


def worktree_path(workdir, run_id) -> pathlib.Path:
    """指定 run 的 worktree 路径（校验 run_id）。"""
    return worktrees_dir(workdir) / _validate_run_id(run_id)


def is_git_repo(workdir) -> bool:
    """工作区是否位于 git 检出内（git 不可用 → False）。"""
    try:
        proc = subprocess.run(
            ["git", "-C", str(workdir), "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        # git 不可用/超时 → 非 git（调用方 loud 拒绝：见 create）
        return False
    return proc.returncode == 0 and proc.stdout.strip() == "true"


def _git(workdir, *args: str, timeout: int = 120) -> str:
    """运行 git 子命令；非零退出 → WorktreeError（stderr 透出）。"""
    try:
        proc = subprocess.run(["git", "-C", str(workdir), *args],
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout,
                              check=False)
    except OSError as exc:
        raise WorktreeError(f"git unavailable: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise WorktreeError(
            f"git timeout: git {' '.join(args)}") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[:500]
        raise WorktreeError(
            f"git {' '.join(args)} failed（exit {proc.returncode}）: {detail}")
    return proc.stdout or ""


def create(workdir, run_id) -> pathlib.Path:
    """创建隔离 worktree（detached HEAD）并返回路径；失败 loud。"""
    if not is_git_repo(workdir):
        raise WorktreeError(f"not a git repository（或 git 不可用）: {workdir}")
    path = worktree_path(workdir, run_id)
    if path.exists():
        raise WorktreeError(f"worktree already exists: {path}")
    _git(workdir, "worktree", "add", "--detach", str(path), "HEAD")
    logger.info("worktree created: %s", path)
    return path


def list_worktrees(workdir) -> list:
    """列出该仓库全部 worktree 路径（porcelain 解析）。"""
    out = _git(workdir, "worktree", "list", "--porcelain")
    paths = []
    for line in out.splitlines():
        if line.startswith("worktree "):
            paths.append(pathlib.Path(line[len("worktree "):].strip()))
    return paths


def remove(workdir, run_id, force: bool = True) -> None:
    """移除 worktree；失败 loud。

    `force=True`：未提交改动随「用户显式丢弃」承担（W5 语义）。
    """
    path = worktree_path(workdir, run_id)
    args = ["worktree", "remove"]
    if force:
        args.append("--force")
    args.append(str(path))
    _git(workdir, *args)
    logger.info("worktree removed: %s", path)


def prune(workdir) -> None:
    """清理失效 worktree 元数据（不删活跃检出）。"""
    _git(workdir, "worktree", "prune")


# ---------------- run ↔ worktree 绑定（恢复路由） ----------------

def run_record_path(state_root, run_id) -> pathlib.Path:
    """隔离 run 的 worktree 绑定标记路径（state_root/.wuxing/runs/<rid>/worktree.json）。"""
    return (pathlib.Path(state_root) / ".wuxing" / "runs"
            / _validate_run_id(run_id) / "worktree.json")


def record_run(state_root, run_id, worktree) -> None:
    """记录 run ↔ worktree 绑定（原子写）——重启后恢复路由读。"""
    from wuxing.atomic_write import atomic_write_text
    p = run_record_path(state_root, run_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(p, json.dumps({"worktree": str(worktree)},
                                    ensure_ascii=False))


def run_worktree(state_root, run_id) -> pathlib.Path | None:
    """读取 run ↔ worktree 绑定；无标记/已丢弃/损坏 → None（诚实缺省）。"""
    p = run_record_path(state_root, run_id)
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # 标记损坏/不可读 → 无绑定（恢复回落主工作区——不造假路径）
        return None
    wt = str(data.get("worktree") or "")
    if not wt:
        return None
    path = pathlib.Path(wt)
    return path if path.is_dir() else None   # 已丢弃 → 无绑定


# ---------------- Review / Apply / Discard（T5） ----------------

_EXCLUDE_WUXING = (":(exclude).wuxing",)


def _is_internal(rel: str) -> bool:
    """引擎内部面（.wuxing/）——永不进入 Review/Apply。"""
    p = str(rel).replace("\\", "/")
    return p.startswith(".wuxing/") or "/.wuxing/" in p


def changes(main_root, run_id) -> list:
    """worktree 变更清单（`git status --porcelain -z`；排除 `.wuxing/`）。"""
    path = worktree_path(main_root, run_id)
    if not path.is_dir():
        raise WorktreeError(f"worktree 不存在: {path}")
    out = _git(path, "status", "--porcelain", "-z")
    items = []
    parts = out.split("\0")
    i = 0
    while i < len(parts):
        entry = parts[i]
        i += 1
        if not entry:
            continue
        status = entry[:2].strip() or "?"
        rel = entry[3:]
        if status[:1] in ("R", "C") and i < len(parts):
            i += 1   # rename/copy：下一项为源路径（展示用目标路径）
        if _is_internal(rel):
            continue
        items.append({"status": status, "path": rel})
    return items


def _staged_diff(path: pathlib.Path) -> str:
    """暂存全量后取 cached diff（含未跟踪新文件），随后还原暂存（无副作用）。"""
    _git(path, "add", "-A")
    try:
        return _git(path, "diff", "--cached", "HEAD", "--", ".",
                    *_EXCLUDE_WUXING)
    finally:
        try:
            _git(path, "reset", "-q")
        except WorktreeError as exc:
            logger.debug("暂存还原失败（下次自愈）：%s", exc)


def diff(main_root, run_id, max_chars: int = 20000) -> str:
    """变更预览（含未跟踪新文件；排除 `.wuxing/`；超长截断）。"""
    path = worktree_path(main_root, run_id)
    if not path.is_dir():
        raise WorktreeError(f"worktree 不存在: {path}")
    out = _staged_diff(path)
    if len(out) > max_chars:
        out = out[:max_chars] + "\n…（diff 超长已截断）"
    return out


def apply(main_root, run_id) -> dict:
    """显式应用 worktree 变更到主检出（W5；冲突/失败 loud 不自动消解）。

    只含非 `.wuxing/` 变更；返回 `{"files": 变更文件数}`。
    """
    path = worktree_path(main_root, run_id)
    if not path.is_dir():
        raise WorktreeError(f"worktree 不存在: {path}")
    patch = _staged_diff(path)
    files = sum(1 for line in patch.splitlines()
                if line.startswith("diff --git "))
    if files == 0:
        return {"files": 0}
    # 经临时文件传递（UTF-8 字节——避开 Windows 控制台/输入编码差异）
    import tempfile
    fd, tmp = tempfile.mkstemp(suffix=".patch")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(patch)
        _git(main_root, "apply", "--whitespace=nowarn", tmp)
    finally:
        try:
            os.unlink(tmp)
        except OSError as exc:
            logger.debug("补丁临时文件清理失败（不阻断）：%s", exc)
    return {"files": files}


def discard(main_root, run_id) -> None:
    """丢弃 worktree（强制移除；主检出零改动；已丢弃幂等）。"""
    path = worktree_path(main_root, run_id)
    if not path.is_dir():
        return
    remove(main_root, run_id, force=True)


# ---------------- setup 声明（CU9） ----------------

SETUP_FILE = "wuxing.worktree.json"
_SETUP_ALT = ".wuxing/worktree.json"
DEFAULT_SETUP_TIMEOUT_S = 300.0
_MAX_SETUP_OUTPUT = 4000


def setup_file(workdir) -> pathlib.Path | None:
    """setup 声明路径：根 `wuxing.worktree.json` 优先，`.wuxing/worktree.json`
    回退；无 → None。"""
    root = pathlib.Path(workdir)
    for rel in (SETUP_FILE, _SETUP_ALT):
        p = root / rel
        if p.is_file():
            return p
    return None


def load_setup(workdir) -> dict:
    """读取 setup 声明；无声明 → {}（零行为）；损坏/非对象 → loud 拒绝。"""
    p = setup_file(workdir)
    if p is None:
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise WorktreeError(f"setup 声明不可读/非法 JSON: {p}: {exc}") from exc
    if not isinstance(data, dict):
        raise WorktreeError(f"setup 声明必须是 JSON 对象: {p}")
    return data


def _as_cmd_list(raw, key: str) -> list:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise WorktreeError(f"setup 字段必须是命令数组: {key}")
    return [str(c) for c in raw]


def setup_commands(decl: dict, platform: str | None = None) -> list:
    """合并通用 `setup` + 平台特定（nt → setup_windows；其余 → setup_unix）。"""
    plat = platform or ("nt" if os.name == "nt" else "posix")
    key = "setup_windows" if plat == "nt" else "setup_unix"
    return (_as_cmd_list(decl.get("setup"), "setup")
            + _as_cmd_list(decl.get(key), key))


def _safe_under(root: pathlib.Path, rel: str) -> pathlib.Path:
    """相对路径归一化并限定在 root 内（防声明穿越）。"""
    target = (root / rel).resolve()
    if not target.is_relative_to(root.resolve()):
        raise WorktreeError(f"setup 路径越出工作区: {rel!r}")
    return target


def _run_setup_command(cmd: str, cwd, timeout_s: float) -> None:
    """执行单条 setup 命令；失败/超时 → WorktreeError（输出截断透出）。"""
    try:
        proc = subprocess.run(cmd, shell=True, cwd=str(cwd),
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout_s, check=False)
    except subprocess.TimeoutExpired as exc:
        raise WorktreeError(
            f"setup command timeout（>{timeout_s:g}s）: {cmd}") from exc
    except OSError as exc:
        raise WorktreeError(f"setup command 无法执行: {cmd}: {exc}") from exc
    if proc.returncode != 0:
        detail = ((proc.stderr or "") + "\n" + (proc.stdout or "")).strip()
        raise WorktreeError(
            f"setup command 失败（exit {proc.returncode}）: {cmd}: "
            f"{detail[:_MAX_SETUP_OUTPUT]}")


def run_setup(main_root, worktree_root,
              timeout_s: float = DEFAULT_SETUP_TIMEOUT_S) -> dict:
    """执行 setup 声明（env_copy → setup 命令）；失败不抛，返回可见结果。

    - 声明读取自 `main_root`（主检出权威——未提交声明也可用）；
    - `env_copy` 从主检出复制到 worktree（创建父目录；源缺失=失败可见）；
    - 命令 cwd=worktree（安装发生在检出内），按序执行、失败即停；
    - 返回 `{"ok": bool, "commands": int, "copied": int, "error": str}`。
      失败由调用方处理（run 标 degraded + 事件——W4 语义）。
    """
    out = {"ok": True, "commands": 0, "copied": 0, "error": ""}
    try:
        decl = load_setup(main_root)
        main = pathlib.Path(main_root)
        wt = pathlib.Path(worktree_root)
        for rel in _as_cmd_list(decl.get("env_copy"), "env_copy"):
            src = _safe_under(main, rel)
            dst = _safe_under(wt, rel)
            if not src.is_file():
                raise WorktreeError(f"env_copy 源文件缺失: {rel}")
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            out["copied"] += 1
        for cmd in setup_commands(decl):
            _run_setup_command(cmd, wt, timeout_s)
            out["commands"] += 1
    except WorktreeError as exc:
        out["ok"] = False
        out["error"] = str(exc)
    return out
