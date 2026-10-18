"""G6：截断全文落盘（「截断≠丢弃」）。

设计：`docs/WUXING_截断全文落盘_G6_设计_2026-09-26.md`。
- 位置：`<workdir>/.wuxing/truncated/`；命名 `{seq:06d}-{unit}.txt`（序号只增不复用）
- 并发：进程内按目录锁 + O_EXCL 独占创建（并行单元/多进程不重号）
- 保留：数量 ≤ MAX_FILES 且总字节 ≤ MAX_BYTES；每次落盘后按序号升序**从最旧删**
- 读回：`read_file` 对 `.wuxing/truncated/` 精确例外（workspace._safe_path）
- 韧性：落盘失败返回 None（调用方注记不带路径）——观测不阻断
"""
import logging
import pathlib
import re
import threading

logger = logging.getLogger(__name__)

REL_DIR = pathlib.Path(".wuxing") / "truncated"
MAX_FILES = 50
MAX_BYTES = 64 * 1024 * 1024
_SEQ_RE = re.compile(r"^(\d{6,})-")
_NAME_OK = re.compile(r"[^A-Za-z0-9._-]")

_locks: dict = {}
_locks_guard = threading.Lock()


def _lock_for(directory: pathlib.Path) -> threading.Lock:
    key = str(directory)
    with _locks_guard:
        lock = _locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _locks[key] = lock
        return lock


def _sanitize(unit: str) -> str:
    name = _NAME_OK.sub("_", str(unit or "").strip())
    return name or "unit"


def _entries(directory: pathlib.Path) -> list:
    """[(seq, path, size)]——按序号升序；坏名/不可读跳过（韧性）。"""
    out = []
    try:
        children = list(directory.iterdir())
    except OSError:
        return []
    for p in children:
        try:
            if not p.is_file():
                continue
            m = _SEQ_RE.match(p.name)
            if not m:
                continue
            out.append((int(m.group(1)), p, p.stat().st_size))
        except OSError:
            continue
    out.sort(key=lambda x: x[0])
    return out


def prune_truncated(workdir) -> int:
    """按序号升序（最旧先）删除直至满足双上限；返回删除数（失败跳过）。"""
    directory = pathlib.Path(workdir) / REL_DIR
    entries = _entries(directory)
    removed = 0
    total = sum(e[2] for e in entries)
    while entries and (len(entries) > MAX_FILES or total > MAX_BYTES):
        _seq, path, size = entries.pop(0)
        try:
            path.unlink()
        except OSError:
            continue  # 删不掉跳过（下次再试）；不虚减 total
        total -= size
        removed += 1
    return removed


def dump_truncated(workdir, text: str, unit: str = "") -> str | None:
    """落盘全文；返回相对工作区 posix 路径；失败返回 None（不抛）。"""
    content = str(text or "")
    if content == "":
        return None
    root = pathlib.Path(workdir)
    directory = root / REL_DIR
    name_tail = _sanitize(unit)
    with _lock_for(directory):
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError:
            # 目录创建失败（权限/竞态）→ None（落盘不可用时调用方保留截断输出）
            return None
        for _ in range(64):  # O_EXCL 冲突重试（跨进程/极端并发）
            entries = _entries(directory)
            seq = (entries[-1][0] + 1) if entries else 1
            path = directory / f"{seq:06d}-{name_tail}.txt"
            try:
                with open(path, "x", encoding="utf-8") as f:
                    f.write(content)
            except FileExistsError:
                continue
            except OSError as e:
                logger.warning("截断全文落盘失败：%s", e)
                return None
            prune_truncated(root)
            return (REL_DIR / path.name).as_posix()
    return None
