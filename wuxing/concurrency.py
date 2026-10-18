"""工具并发分级放行（2026-09-11 用户裁决）——缓速/阻止/滞回 + 重入安全。

语义（设计：docs/WUXING_工具并发分级放行设计_2026-09-11.md）：
- 全局在跑工具数 < soft（默认 64=8×8 目标）→ 正常放行（零延迟）
- [soft, hard)（默认 [64,100)）→ 缓速放行（每次获取前 +delay_ms）
- >= hard（默认 100=10×10 硬限）→ 阻止放行（等待前批完成）
- 回落 < soft → 自动恢复正常放行（滞回）
- 重入工具（delegate——内部会跑子 Runner 工具）不占额度（防死锁）
"""
import threading
import time


class ToolConcurrencyLimiter:
    def __init__(self, soft: int = 64, hard: int = 100, delay_ms: int = 25):
        self.soft = max(1, int(soft))
        self.hard = max(self.soft, int(hard))
        self.delay_ms = max(0, int(delay_ms))
        self._active = 0
        self._cond = threading.Condition()
        self._stats = {"throttled": 0, "blocked": 0}

    def acquire(self) -> bool:
        """获取放行（按分级阻塞/延迟）；返回本次是否走缓速档。"""
        slow = False
        while True:
            with self._cond:
                if self._active < self.hard:
                    slow = self._active >= self.soft
                    self._active += 1
                    break
                self._stats["blocked"] += 1
                self._cond.wait(timeout=0.2)
        if slow:
            self._stats["throttled"] += 1
            if self.delay_ms:
                time.sleep(self.delay_ms / 1000)
        return slow

    def release(self):
        with self._cond:
            self._active = max(0, self._active - 1)
            self._cond.notify_all()

    @property
    def active(self) -> int:
        with self._cond:
            return self._active

    def stats(self) -> dict:
        with self._cond:
            return {"active": self._active, "soft": self.soft,
                    "hard": self.hard, **self._stats}


_LIMITER = ToolConcurrencyLimiter()
_CONFIGURED = False


def get_limiter() -> ToolConcurrencyLimiter:
    return _LIMITER


def configure(soft: int, hard: int, delay_ms: int) -> ToolConcurrencyLimiter:
    """显式重配（强制重建、统计清零——测试/工具后门语义保留）。"""
    global _LIMITER, _CONFIGURED
    _LIMITER = ToolConcurrencyLimiter(soft=soft, hard=hard, delay_ms=delay_ms)
    _CONFIGURED = True
    return _LIMITER


def ensure_configured(soft: int, hard: int,
                      delay_ms: int) -> ToolConcurrencyLimiter:
    """确保进程级限流器已配置（幂等——不重建、不丢统计）。

    壳 P1 对齐项①（第七轮审查）：多工作区（多 Engine 同进程）场景——
    Engine 构造不得替换现役实例/重置统计；**首个配置生效**（进程级
    统一策略）；需重配走 configure()（显式后门）。
    """
    if not _CONFIGURED:
        return configure(soft=soft, hard=hard, delay_ms=delay_ms)
    return _LIMITER
