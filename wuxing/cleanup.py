"""E3-5（CU10）：运行时产物清理纪律——统一清理机制（G6 语义推广）。

设计（计划 `docs/plans/2026-10-04-wuxing-cleanup-discipline.md`）：
- `prune_dir`：目录 + 模式 + 双上限（文件数 / 字节）→ **按 mtime 最旧先删**；
  失败跳过（下次再试，不虚减计数）；空/缺目录幂等；返回 `{removed, freed}`。
- `prune_dirs`：目录批次（E2E artifacts）保留最近 K 个——最旧 `rmtree`。
- `maybe_cleanup`：任务收口触发的**节流**清理（debounce：`.wuxing/.cleanup_stamp`
  间隔 ≥ `cleanup_interval_s`）——扫 sessions / reports；动作落 trace `cleanup`。

边界：只清 `.wuxing/` 内部（sessions / reports）与调用方显式给出的目录；
**绝不**扩展到用户交付物目录。无后台线程 / 无定时器（诚实：机制不常驻）。
"""
import logging
import pathlib
import shutil
import time

logger = logging.getLogger(__name__)

# 字节轴默认（48 MiB——sessions/reports 同款；数量轴走配置）
DEFAULT_MAX_BYTES = 48 * 1024 * 1024


def prune_dir(directory, pattern: str, max_files: int, max_bytes: int) -> dict:
    """按 mtime 最旧先删，直至满足数量/字节双上限；返回清理统计。

    空目录 / 缺目录 → `{"removed": 0, "freed": 0}`（幂等）。
    """
    out = {"removed": 0, "freed": 0}
    directory = pathlib.Path(directory)
    entries = []
    try:
        for p in directory.glob(pattern):
            try:
                if not p.is_file():
                    continue
                st = p.stat()
            except OSError:
                continue
            entries.append((p, st.st_mtime, st.st_size))
    except OSError:
        return out
    entries.sort(key=lambda x: (x[1], str(x[0])))
    total = sum(e[2] for e in entries)
    while entries and (len(entries) > max(0, int(max_files))
                       or total > max(0, int(max_bytes))):
        path, _mtime, size = entries.pop(0)
        try:
            path.unlink()
        except OSError:
            continue  # 删不掉跳过（下次再试）；不虚减 total
        total -= size
        out["removed"] += 1
        out["freed"] += size
    return out


def prune_dirs(base, pattern: str, keep: int) -> dict:
    """目录批次保留最近 `keep` 个（mtime 最旧 `rmtree`）；失败跳过。

    E2E 批次产物（`e2e/shell/.runtime/artifacts/<ts>/`）等本地资产纪律。
    """
    out = {"removed": 0, "freed": 0}
    base = pathlib.Path(base)
    entries = []
    try:
        for p in base.glob(pattern):
            try:
                if not p.is_dir():
                    continue
                entries.append((p, p.stat().st_mtime))
            except OSError:
                continue
    except OSError:
        return out
    entries.sort(key=lambda x: (x[1], str(x[0])))
    while entries and len(entries) > max(0, int(keep)):
        path, _mtime = entries.pop(0)
        try:
            shutil.rmtree(path)
        except OSError:
            continue
        out["removed"] += 1
    return out


def maybe_cleanup(workdir, cfg, trace=None, now=None, fields=None) -> dict:
    """收口触发（debounce）：sessions/reports 双上限清理；动作落 trace。

    - `now`：注入时钟（测试用；None=当前时间）。
    - `fields`：调用方 trace 上下文字段（如 conversation_round——trace 契约）。
    - 返回 `{"ran": bool, "removed": int, "freed": int}`。
    """
    now = time.time() if now is None else float(now)
    result = {"ran": False, "removed": 0, "freed": 0}
    if not bool(getattr(cfg, "cleanup_enabled", True)):
        return result
    root = pathlib.Path(workdir)
    stamp = root / ".wuxing" / ".cleanup_stamp"
    interval = max(0, int(getattr(cfg, "cleanup_interval_s", 3600) or 0))
    last = None
    try:
        last = float(stamp.read_text(encoding="utf-8").strip() or "0")
    except (OSError, ValueError):
        last = None  # 无时间戳（首次/损坏）→ 视为可执行
    if interval > 0 and last is not None and (now - last) < interval:
        return result
    result["ran"] = True
    targets = (
        (root / ".wuxing" / "sessions", "*.jsonl",
         int(getattr(cfg, "cleanup_sessions_max", 300) or 300)),
        (root / ".wuxing" / "reports", "*",
         int(getattr(cfg, "cleanup_reports_max", 300) or 300)),
    )
    for directory, pattern, max_files in targets:
        if max_files <= 0:
            continue
        stats = prune_dir(directory, pattern, max_files, DEFAULT_MAX_BYTES)
        result["removed"] += stats["removed"]
        result["freed"] += stats["freed"]
    try:
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.write_text(str(now), encoding="utf-8")
    except OSError as exc:
        # 时间戳落盘失败：清理已执行；下次调用会再执行（可接受——不静默吞错）
        logger.debug("清理时间戳写入失败（下次重执行）：%s", exc)
    if trace is not None:
        try:
            trace.log("cleanup", "", "", interval_s=interval, **result,
                      **(fields or {}))
        except Exception as exc:  # 观测不阻断——trace 自身已兜底
            logger.debug("cleanup trace 写入失败（观测不阻断）：%s", exc)
    return result
