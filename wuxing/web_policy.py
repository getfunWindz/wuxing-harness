"""E2-5：web_fetch 网络策略（纯函数）——域名 allow/deny · 私网判定 · scheme 白名单。

纪律：本模块零网络、可测；DNS 解析复检走 `resolve_private`（fetch 路径每跳调用，
测试可注入/短路）。`is_private_host` 只做语法判定（IP 字面量 + localhost 类名）。
"""
import ipaddress
import socket
import urllib.parse

_SCHEMES = ("http", "https")


def _normalize(host: str) -> str:
    return str(host or "").strip().lower().rstrip(".")


def _as_ip(host: str):
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        # 非 IP 字面量（域名/非法格式）——调用方按名字路径继续处理
        return None


def _ip_blocked(ip) -> bool:
    return bool(ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified)


def is_private_host(host: str) -> bool:
    """语法级私网/保留判定（无 DNS）：IP 字面量命中 → True；localhost 类名 →
    True；空值/非法 → True（fail-closed）。"""
    h = _normalize(host)
    if not h:
        return True
    ip = _as_ip(h)
    if ip is not None:
        return _ip_blocked(ip)
    return h == "localhost" or h.endswith(".localhost")


def host_allowed(host: str, allow=(), deny=()) -> bool:
    """deny 优先；allow 非空=仅白名单（精确或子域后缀）；大小写不敏感。"""
    h = _normalize(host)
    deny_set = {_normalize(d) for d in (deny or ()) if _normalize(d)}
    allow_set = {_normalize(a) for a in (allow or ()) if _normalize(a)}

    def _match(entry: str) -> bool:
        return h == entry or h.endswith("." + entry)

    if any(_match(d) for d in deny_set):
        return False
    if allow_set:
        return any(_match(a) for a in allow_set)
    return True


def check_url(url: str, allow=(), deny=()) -> None:
    """URL 策略校验：scheme ∈ {http, https}；host 存在且非私网；域名表通过。

    非法 → ValueError（调用方补 `policy:` 前缀统一归因）。
    """
    raw = str(url or "").strip()
    if not raw:
        raise ValueError("empty url")
    try:
        parsed = urllib.parse.urlsplit(raw)
    except ValueError as exc:
        raise ValueError(f"invalid url: {exc}") from exc
    scheme = (parsed.scheme or "").lower()
    if scheme not in _SCHEMES:
        raise ValueError(f"scheme not allowed: {scheme or '(none)'}")
    host = parsed.hostname or ""
    if not host:
        raise ValueError("missing host")
    if is_private_host(host):
        raise ValueError(f"private/loopback host rejected: {host}")
    if not host_allowed(host, allow=allow, deny=deny):
        raise ValueError(f"domain not allowed: {host}")


def resolve_private(host: str) -> bool:
    """DNS 解析复检（SSRF）：解析出的地址存在私网/保留 → True；

    解析失败 → True（fail-closed）。**fetch 路径每跳调用**（DNS rebinding
    TOCTOU 残余按计划风险 1 文档化）。"""
    h = _normalize(host)
    if is_private_host(h):
        return True
    try:
        infos = socket.getaddrinfo(h, None)
    except OSError:
        # 解析失败 fail-closed：按私网拒绝（SSRF 防护优先于可用性）
        return True
    for info in infos:
        ip = _as_ip(info[4][0])
        if ip is None or _ip_blocked(ip):
            return True
    return False
