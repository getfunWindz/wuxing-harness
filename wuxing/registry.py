"""域注册表（Q5-B：机制层常驻；注册器轻量自研——参考 DSH seam 取舍）。

P8.1：任务级启用集——条件域（user）默认未启用，按语义激活。
get() 语义：仅启用域可获取（未启用条件域抛 KeyError——明确失败）。
"""
from wuxing.config import EngineConfig
from wuxing.domains import DEFAULT_DOMAINS
from wuxing.protocols import DomainDefinition


class DomainRegistry:
    def __init__(self, cfg: EngineConfig, domains: dict | None = None):
        self._domains = dict(domains) if domains else dict(DEFAULT_DOMAINS)
        # 仅保留配置中启用的域
        self._domains = {k: v for k, v in self._domains.items()
                         if k in cfg.default_domains}
        # 任务级启用集（P8.1）：默认 = 非条件域（条件域按语义激活）
        self._active = [d for d, defn in self._domains.items()
                        if not defn.conditional]

    def active_ids(self) -> list:
        return list(self._active)

    def activate(self, domain_ids: list):
        """激活条件域（幂等）。"""
        for did in domain_ids:
            if did not in self._domains:
                raise KeyError(f"unknown domain: {did}")
            if did not in self._active:
                self._active.append(did)

    def register(self, domain_id: str, definition) -> None:
        """动态注册域（双模式批 3：循迹设计域——按需挂载，不进默认配置）。"""
        self._domains[domain_id] = definition
        if domain_id not in self._active and not definition.conditional:
            self._active.append(domain_id)

    def get(self, domain_id: str) -> DomainDefinition:
        if domain_id not in self._active:
            raise KeyError(f"domain not active: {domain_id}")
        return self._domains[domain_id]

    def all_domain_ids(self) -> list:
        return list(self._domains.keys())

    def is_conditional(self, domain_id: str) -> bool:
        """P8：条件域（低频域按需启用——user 2.5% 数据支撑）。"""
        return self._domains[domain_id].conditional if domain_id in self._domains else False
