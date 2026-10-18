"""确认关口（Q6-C/Q13-C：分层把关——关键碎片挂起，阈值可调）。

判定：confirm_threshold 0=全自动 1=全确认（默认全自动）。
域规则：always_confirm_domains（verify 默认）覆盖阈值。
P8.1：registry 注入——未启用（条件域）不触发确认。
回调：on_confirm(cb) 注册确认处理；notify(unit_id, approve, reason) 触发。
"""
from dataclasses import dataclass


@dataclass
class ConfirmGate:
    cfg: object
    always_confirm_domains: tuple = ("verify", "user")
    registry: object = None   # P8.1：域注册表（条件域启用检查）

    def __post_init__(self):
        self._listener = None

    def _domain_active(self, domain_id: str) -> bool:
        if self.registry is None:
            return True
        return domain_id in self.registry.active_ids()

    def needs_confirm(self, domain_id: str, unit_id: str,
                      difficulty: int = 1) -> bool:
        if not self._domain_active(domain_id):
            return False  # 未启用（条件域）不确认
        if domain_id in self.always_confirm_domains:
            return True
        t = self.cfg.confirm_threshold
        if t <= 0.0:
            return False
        if t >= 1.0:
            return True
        # 中间阈值（P6）：难度加权——difficulty 归一化后 >= 门槛才确认
        d_norm = (difficulty - 1) / 4.0 if difficulty >= 1 else 0.0
        return d_norm >= self.cfg.confirm_threshold_difficulty

    def on_confirm(self, cb):
        self._listener = cb

    def notify(self, unit_id: str, approve: bool, reason: str = ""):
        if self._listener:
            self._listener(unit_id, approve, reason)
