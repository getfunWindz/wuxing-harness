"""壳服务鉴权档（O5 安全门 T1）——token 校验 + 失败限速 + 审计日志。

口径（`docs/WUXING_O5内网穿透研究_2026-10-15.md` §4/§8-T1；用户裁决 Q6）：
- loopback 绑定默认免鉴权（现状不变）；非环回绑定由 launcher 强制装配本档（fail-closed）；
- token 解析：显式参数 > 环境变量 WUXING_SHELL_TOKEN > 凭据文档（同 ref）；
- 请求通行：Authorization: Bearer / X-Wuxing-Token 头 / 会话 cookie（?token= 首次换发）；
- 失败限速：按来源 IP 滑动窗口；审计事件只记 IP 与路径（永不记 token 值）。
"""
import hmac
import ipaddress
import logging
import time
from collections import defaultdict, deque

from wuxing.credentials import resolve as resolve_credential

logger = logging.getLogger("wuxing.shell.auth")

TOKEN_REF = "WUXING_SHELL_TOKEN"
SESSION_COOKIE = "wuxing_session"


def is_loopback_host(host: str) -> bool:
    """绑定地址是否环回（决定是否强制鉴权）。"""
    h = (host or "").strip().strip("[]").lower()
    if h == "localhost":
        return True
    if not h:
        return False
    try:
        return ipaddress.ip_address(h.split("%", 1)[0]).is_loopback
    except ValueError:
        # 非法 IP 字面量（如主机名）——非环回（由按需鉴权与白名单处理）
        return False


def resolve_shell_token(explicit: str | None = None) -> str | None:
    """token 解析：显式 > env WUXING_SHELL_TOKEN > 凭据文档；未配置 → None。"""
    if explicit:
        return explicit
    return resolve_credential(TOKEN_REF)


def token_from_headers(headers) -> str | None:
    """从请求头提取候选 token：Bearer 优先，其次 X-Wuxing-Token。"""
    authz = (headers.get("Authorization", "") or "").strip()
    if authz.lower().startswith("bearer "):
        return authz[7:].strip() or None
    tok = (headers.get("X-Wuxing-Token", "") or "").strip()
    return tok or None


def cookie_token(cookie_header: str, name: str = SESSION_COOKIE) -> str | None:
    """从 Cookie 头提取会话值（精确键匹配；无 → None）。"""
    for part in (cookie_header or "").split(";"):
        k, _, v = part.strip().partition("=")
        if k == name and v:
            return v
    return None


class AuthGuard:
    """token 校验 + 失败限速（滑动窗口；按来源 IP 独立）。

    - verify(value)：常量时间比较；
    - is_rate_limited(ip) / note_failure(ip)：窗口内计数自动过期；
    - 限速期内一律拒绝（含正确 token——恶意窗口内不放大校验资源）。
    """

    def __init__(self, token: str, *, max_failures: int = 10,
                 window_s: float = 60.0, clock=time.monotonic):
        if not token:
            raise ValueError("token 不能为空")
        self._token = token
        self._max_failures = int(max_failures)
        self._window_s = float(window_s)
        self._clock = clock
        self._failures: dict[str, deque] = defaultdict(deque)

    @property
    def window_s(self) -> float:
        return self._window_s

    def verify(self, value: str | None) -> bool:
        if not value:
            return False
        return hmac.compare_digest(self._token, value)

    def _prune(self, ip: str, now: float) -> deque:
        q = self._failures[ip]
        while q and now - q[0] > self._window_s:
            q.popleft()
        return q

    def is_rate_limited(self, ip: str) -> bool:
        now = self._clock()
        return len(self._prune(ip, now)) >= self._max_failures

    def note_failure(self, ip: str) -> bool:
        """记一次失败；返回是否达到限速阈值。"""
        now = self._clock()
        q = self._prune(ip, now)
        q.append(now)
        tripped = len(q) >= self._max_failures
        if tripped:
            logger.warning("auth.rate_limited ip=%s failures=%d", ip, len(q))
        return tripped
