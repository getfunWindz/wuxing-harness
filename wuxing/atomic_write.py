"""原子写（tmp + replace + Windows 瞬态占用重试）——引擎与壳共用。

背景：Windows 下 `os.replace` 会被杀软扫描/索引器短暂持锁（PermissionError），
项目内多处原子写曾各写各的（manager/workspace 有重试，config/state 漏）——
统一于此，消除「全量套件负载下偶发写失败」类 flake。

纪律：重试耗尽仍失败 → 抛出（调用方决定是否降级）；tmp 命名固定为
`<name>.tmp`，失败残留由下一轮写入覆盖（不主动清理，避免误删并发写）。
"""
import os
import pathlib
import time


def atomic_write_text(path, text: str, *, attempts: int = 3,
                      encoding: str = "utf-8") -> None:
    """原子写文本：先写 tmp 再 replace；瞬态占用失败按 20/40/60ms 重试。"""
    target = pathlib.Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    last: OSError | None = None
    for attempt in range(max(1, attempts)):
        try:
            tmp.write_text(text, encoding=encoding)
            os.replace(tmp, target)
            return
        except OSError as exc:
            last = exc
            time.sleep(0.02 * (attempt + 1))
    if last is not None:
        raise last
    raise OSError(f"atomic_write_text 失败：{target}")


def read_text_retry(path, *, attempts: int = 3, encoding: str = "utf-8",
                    errors: str = "replace") -> str | None:
    """读文本（与写侧对称的瞬态占用重试）——重试耗尽返回 None。

    场景：追加写与读取并发（同进程双工作区）+ Windows 杀软/索引器扫描，
    会使 `read_text` 偶发 PermissionError（共享冲突）——不得因此静默丢数据。
    """
    target = pathlib.Path(path)
    for attempt in range(max(1, attempts)):
        try:
            return target.read_text(encoding=encoding, errors=errors)
        except OSError:
            time.sleep(0.02 * (attempt + 1))
    return None
