"""路径级共享锁注册表（G8）：进程内多 Engine 实例/多 run 对同一文件互斥。

背景：trace/provenance/cache/brain/tickets 等只有实例级锁——并行 run（多
Engine 实例）时锁不互斥；本模块提供按「规范化路径」共享的 RLock，供各写入面
统一获取（同一路径 → 同一锁对象；不同路径互不阻塞）。

键的规范化（M2 实测教训）：不用 ``Path.resolve()``——Windows 下同一文件会
时而出 ``\\?\\`` 扩展前缀形式（exists/lexical 解析差异），导致同一文件被
切成两把锁。改为：abspath → realpath（失败回退）→ 剥 ``\\?\\`` 前缀 → normcase。

范围：进程内（单壳服务）。跨进程并发在 G8 范围外（设计 §6）。
"""
import os
import threading

_REGISTRY: dict[str, threading.RLock] = {}
_REG_GUARD = threading.Lock()


def _canonical(path) -> str:
    raw = os.path.abspath(str(path))
    try:
        real = os.path.realpath(raw)
    except OSError:
        real = raw
    real = real.removeprefix("\\\\?\\")
    return os.path.normcase(real)


def lock_for(path) -> threading.RLock:
    """规范化路径 → 共享 RLock（不存在则创建；幂等）。"""
    key = _canonical(path)
    with _REG_GUARD:
        lock = _REGISTRY.get(key)
        if lock is None:
            lock = threading.RLock()
            _REGISTRY[key] = lock
        return lock
