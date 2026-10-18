"""MCP 桥（P2：外部 MCP server 的工具无缝接入 Tool Protocol）。

stdio 连接：McpServerConfig{name, command, args} →
  ClientSession.list_tools() → 每个工具包装为 McpToolAdapter(Tool)。

生命周期：E1（企业级审查 2026-09-07）——常驻连接池（McpConnectionPool）：
  首次调用建连并复用（initialize 一次——此前每次 execute 独立连接：
  spawn+init+call+关闭 秒级开销拖慢工具链）；断连自动重连一次；
  mcp session 非线程安全 → 每 server 串行化（不同 server 并行）。
"""
import asyncio
import logging
import re
import threading
import time
from dataclasses import dataclass

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from wuxing.protocols import Tool

logger = logging.getLogger(__name__)


@dataclass
class McpServerConfig:
    name: str
    command: str = ""
    args: list = None
    # R3-2/M2：transport——stdio（command）或 streamable-http（url+headers）
    url: str = None
    headers: dict = None
    # MCP 权限显式声明（最小权限——未声明 = 工具默认拒绝，registry 拦截）
    permissions: dict = None
    # E4（企业级审查）：环境变量白名单 {变量名: 环境变量名}——值=环境变量名
    # （机密不进配置——运行时从 os.environ 读取；未声明=不注入【最小面】）
    env: dict = None

    def __post_init__(self):
        validate_server_name(self.name)


def transport_of(cfg: "McpServerConfig") -> str:
    """transport 推断（M2）：有 url → streamable-http；否则 stdio。"""
    return "streamable-http" if (cfg.url or "").startswith(("http://", "https://")) \
        else "stdio"


def _env_for(cfg: "McpServerConfig") -> dict | None:
    """E4 + R3-2/M3：stdio 子进程环境 = 擦洗后的本机环境（剔除机密）
    再合并显式声明（声明为显式 opt-in——值从 os.environ 取）。

    擦洗规则（DSH 同款）：变量名匹配 KEY/PASSWORD/SECRET/TOKEN（不区分大小写）
    或前缀 WUXING_ 一律剔除——机密不入子进程（除显式声明）。
    """
    import os
    env = scrub_env(os.environ)
    for k, v in (cfg.env or {}).items():
        env[k] = os.environ.get(v, "")
    return env


_SECRET_RE = re.compile(r"KEY|PASSWORD|SECRET|TOKEN", re.IGNORECASE)


def scrub_env(base=None) -> dict:
    """R3-2/M3：环境擦洗（纯函数）——剔除机密变量与 WUXING_* 前缀。"""
    import os
    src = os.environ if base is None else base
    return {k: v for k, v in src.items()
            if not _SECRET_RE.search(k) and not str(k).startswith("WUXING_")}


# R3-2/M4：重连退避（纯函数——池内接线归 T6b）
BACKOFF_BASE_MS = 500
BACKOFF_MAX_MS = 30_000
MAX_ATTEMPTS = 10


def backoff_ms(attempt: int) -> int:
    """指数退避：500ms→1s→2s→…→封顶 30s（attempt 从 1 起）。"""
    attempt = max(attempt, 1)
    return min(BACKOFF_BASE_MS * (2 ** (attempt - 1)), BACKOFF_MAX_MS)


def should_unload(attempt: int) -> bool:
    """达到重试上限 → 卸载该服务器工具（不再重试）。"""
    return attempt >= MAX_ATTEMPTS


class ReconnectBudget:
    """重连预算状态机（R3-2/M4）：失败退避 → 上限卸载；成功重置（稳定即清）。"""

    def __init__(self, now=None):
        self.now = now or time.monotonic
        self.attempts = 0
        self.next_at = 0.0
        self.unloaded = False

    def on_failure(self) -> float:
        """记录一次失败：返回需等待秒数；达上限 → unloaded（返回 0）。"""
        self.attempts += 1
        if should_unload(self.attempts):
            self.unloaded = True
            return 0.0
        wait = backoff_ms(self.attempts) / 1000.0
        self.next_at = self.now() + wait
        return wait

    def on_success(self):
        """成功调用 → 重置预算（连接稳定）。"""
        self.attempts = 0
        self.next_at = 0.0

    def gate(self) -> bool:
        """是否允许立即重试（未到退避时刻 → False）。"""
        return not self.unloaded and self.now() >= self.next_at


def _http_client():
    """streamable-http 客户端工厂（惰性导入——mcp 可选依赖；测试可替换）。"""
    from mcp.client.streamable_http import streamablehttp_client
    return streamablehttp_client


def _open_stream(cfg: "McpServerConfig"):
    """打开传输流（R3-2/T5b）：stdio 或 streamable-http（返回 async 上下文）。"""
    if transport_of(cfg) == "streamable-http":
        return _http_client()(cfg.url, headers=cfg.headers or None)
    params = StdioServerParameters(
        command=cfg.command, args=list(cfg.args or []), env=_env_for(cfg))
    return stdio_client(params)


def _unpack_stream(entered):
    """流上下文产物归一化：stdio (read, write) / http (read, write, ...)。"""
    if isinstance(entered, tuple) and len(entered) >= 2:
        return entered[0], entered[1]
    return entered


# R3-2/M1：工具命名 pinned 契约——mcp__<serverName>__<rawName>
# （serverName 为本地配置名；绝不用远端 serverInfo.name）
_SERVER_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


def validate_server_name(name: str) -> str:
    """serverName 契约校验：[A-Za-z0-9_-]{1,32}（非法 → ValueError 早报）。"""
    if not isinstance(name, str) or not _SERVER_NAME_RE.match(name):
        raise ValueError(
            f"非法 MCP 服务器名：{name!r}（需 [A-Za-z0-9_-]{{1,32}}）")
    return name


def mcp_tool_name(server_name: str, tool_name: str) -> str:
    """命名契约（纯函数）：mcp__<server>__<raw>。"""
    return f"mcp__{validate_server_name(server_name)}__{tool_name}"


class McpConnectionPool:
    """E1 + 2026-09-11 审查修复：常驻连接池——同 server 的连接跨调用复用。

    根因（审查 A1）：生产路径 McpToolAdapter.execute 是同步方法，每次调用
    asyncio.run() 起独立事件循环；而 stdio_client/ClientSession 的 anyio
    流绑定在首个循环——跨循环使用 → 每次重连 + anyio 清理异常刷屏
    （"exit cancel scope in a different task"）。
    修复：专属后台事件循环线程——所有 MCP 调用经 call_tool_blocking 调度到
    同一循环（连接真正复用）；同步 close() 在同一循环内清理。

    - 首次调用建连（stdio_client + initialize）；后续复用（initialize 一次）
    - 每 server 一把 asyncio.Lock：ClientSession 非线程安全 → 同 server 调用串行
      （不同 server 互不阻塞——runner 工具级并发对不同 server 生效）
    - 韧性：调用异常 → 关闭重连一次；仍败 → 上抛（adapter 转为 error）
    - 资源清理：close()/aclose() 释放全部连接（引擎/进程退出——atexit 注册）
    - stats：{server: {connections, calls}}（评测——连接复用率仪表）

    注意：async call_tool 与 sync call_tool_blocking 不混用（前者在调用方
    自己的循环内运行——测试/嵌入场景；混用会触发跨循环锁绑定错误）。
    """

    def __init__(self):
        self._conns = {}  # name -> {cfg, session, lock, broken, connections, calls}
        self._lock = threading.Lock()
        self.stats = {}   # name -> {connections, calls}
        # 专属事件循环（连接复用的前提——anyio 流绑定单一循环）
        self._loop = None
        self._loop_thread = None
        self._loop_guard = threading.Lock()

    # ---------- 专属事件循环 ----------
    def _ensure_loop(self):
        """惰性启动后台事件循环线程（daemon——进程退出不阻塞）。"""
        with self._loop_guard:
            if self._loop is None or self._loop.is_closed():
                loop = asyncio.new_event_loop()
                th = threading.Thread(target=self._run_loop, args=(loop,),
                                      name="wuxing-mcp-pool", daemon=True)
                th.start()
                self._loop, self._loop_thread = loop, th
        return self._loop

    @staticmethod
    def _run_loop(loop):
        asyncio.set_event_loop(loop)
        loop.run_forever()

    def call_tool_blocking(self, cfg: "McpServerConfig", tool_name: str,
                           kwargs: dict, timeout: float = 30.0) -> str:
        """同步入口（同步工具执行路径）：在专属循环内复用常驻连接。

        修复 A1 的关键路径——McpToolAdapter.execute 走这里（不再每次
        asyncio.run 新循环）。
        """
        loop = self._ensure_loop()

        async def _call():
            return await asyncio.wait_for(
                self.call_tool(cfg, tool_name, kwargs), timeout=timeout)

        fut = asyncio.run_coroutine_threadsafe(_call(), loop)
        return fut.result(timeout + 2.0)

    async def call_tool(self, cfg: "McpServerConfig", tool_name: str,
                        kwargs: dict) -> str:
        """经池调用工具（连接复用）；返回文本内容（适配原协议）。"""
        with self._lock:
            entry = self._conns.setdefault(cfg.name, {
                "cfg": cfg, "session": None, "broken": False,
                "connections": 0, "calls": 0, "lock": None,
                "budget": ReconnectBudget()})
            self.stats.setdefault(cfg.name, {"connections": 0, "calls": 0})
            lock = entry["lock"]
            if lock is None:
                # 在调用所属循环内创建（asyncio.Lock 绑定运行循环）
                lock = entry["lock"] = asyncio.Lock()
        # 同 server 串行（session 非线程安全）——asyncio.Lock（专属循环内
        # 等待不阻塞循环线程；threading.Lock 会死锁事件循环）
        async with lock:
            budget = entry["budget"]
            if budget.unloaded:
                raise RuntimeError(
                    f"MCP 服务器 {cfg.name} 不可用（重试上限——已卸载）")
            if not budget.gate():
                await asyncio.sleep(max(0.0, budget.next_at - budget.now()))
            try:
                out = await self._call_or_reconnect(entry, tool_name, kwargs)
                budget.on_success()
                return out
            except Exception:
                # 断连韧性（R3-2/M4）：退避后重连一次；达上限 → 卸载（显式可见）
                wait = budget.on_failure()
                if budget.unloaded:
                    raise RuntimeError(
                        f"MCP 服务器 {cfg.name} 不可用（重试上限——已卸载）") from None
                await self._close(entry)
                if wait:
                    await asyncio.sleep(wait)
                out = await self._call_or_reconnect(entry, tool_name, kwargs)
                budget.on_success()
                return out

    async def _call_or_reconnect(self, entry: dict, tool_name: str,
                                 kwargs: dict) -> str:
        if entry["session"] is None or entry["broken"]:
            await self._open(entry)
        entry["calls"] += 1
        self.stats[entry["cfg"].name]["calls"] = entry["calls"]
        r = await entry["session"].call_tool(tool_name, kwargs)
        parts = [c.text if hasattr(c, "text") else str(c) for c in r.content]
        return "\n".join(parts)

    async def _open(self, entry: dict):
        """建连（stdio_client + ClientSession + initialize）——失败上抛。"""
        cfg = entry["cfg"]
        cm = _open_stream(cfg)
        read, write = _unpack_stream(await cm.__aenter__())
        session = await ClientSession(read, write).__aenter__()
        await session.initialize()
        entry["session"] = session
        entry["broken"] = False
        entry["connections"] += 1
        entry["_cm"] = cm  # 保留引用（关闭时 __aexit__）
        self.stats[cfg.name]["connections"] = entry["connections"]

    async def _close(self, entry: dict):
        """释放连接（幂等——异常静默：清理不是生命线）。"""
        s = entry.get("session")
        entry["session"] = None
        entry["broken"] = True
        cm = entry.pop("_cm", None)
        if s is not None:
            try:
                await s.__aexit__(None, None, None)
            except Exception as exc:
                logger.debug("MCP 会话清理失败（不阻断）：%s", exc)
        if cm is not None:
            try:
                await cm.__aexit__(None, None, None)
            except Exception as exc:
                logger.debug("MCP 上下文清理失败（不阻断）：%s", exc)

    async def aclose(self):
        """异步上下文清理（在事件循环内使用）。"""
        await self._close_all()

    async def _close_all(self):
        with self._lock:
            entries = list(self._conns.values())
            self._conns.clear()
        for e in entries:
            await self._close(e)

    def close(self):
        """同步清理（atexit/测试 finally）：在专属循环内释放连接并停循环。

        幂等；专属循环未启动（仅 async call_tool 用过）时 no-op——
        连接由调用方循环管理。
        """
        loop = self._loop
        if loop is None:
            return
        try:
            fut = asyncio.run_coroutine_threadsafe(self._close_all(), loop)
            fut.result(timeout=5)
        except Exception as exc:
            logger.debug("MCP 连接清理超时（不阻断）：%s", exc)
        try:
            loop.call_soon_threadsafe(loop.stop)
        except Exception as exc:
            logger.debug("MCP 事件循环停止失败（不阻断）：%s", exc)
        th = self._loop_thread
        if th is not None:
            th.join(timeout=2)
        with self._loop_guard:
            self._loop = None
            self._loop_thread = None


def _make_pool() -> "McpConnectionPool":
    """创建连接池并注册进程退出清理（atexit——stdio 子进程不残留）。"""
    import atexit
    pool = McpConnectionPool()
    atexit.register(pool.close)  # 修复 A1：close 为同步（内部调度到专属循环）
    return pool


class McpToolAdapter(Tool):
    def __init__(self, server_name: str, tool_name: str, description: str,
                 input_schema: dict, config: "McpServerConfig", timeout: float = 30.0,
                 pool: "McpConnectionPool | None" = None):
        self._server = server_name
        self._tool = tool_name
        self._desc = description
        self._schema = input_schema
        self._config = config
        self._timeout = timeout  # 阶段 3b：挂起 server 不挂引擎（审查 #19）
        self._pool = pool  # E1：连接池（None=按次连接兜底——测试兼容）
        self.is_mcp = True  # L2-1：MCP 标记——不参与 default_tools 粗筛
                            # （三重闸：显式配置引入 + permissions 声明 + 域白名单）
    def name(self): return mcp_tool_name(self._server, self._tool)
    def description(self): return self._desc
    def input_schema(self): return self._schema
    def permission(self):
        # P3 T2 + MCP 权限配置：显式声明解锁（default 全 False——最小权限）
        perm = {"read": False, "write": False, "execute": False,
                "network": False, "destructive": False}
        declared = (self._config.permissions or {}) if self._config else {}
        for k in perm:
            if k in declared:
                perm[k] = bool(declared[k])
        return perm

    def execute(self, **kwargs):
        from wuxing.protocols import ToolResult
        try:
            if self._pool is not None:
                # 修复 A1：专属循环内复用连接（不再每次 asyncio.run 新建循环）
                content = self._pool.call_tool_blocking(
                    self._config, self._tool, kwargs, timeout=self._timeout)
            else:
                content = asyncio.run(asyncio.wait_for(
                    self._async_call(kwargs), timeout=self._timeout))
            return ToolResult(status="ok", content=content, tool_name=self.name())
        except (asyncio.TimeoutError, TimeoutError):
            return ToolResult(status="error", tool_name=self.name(),
                              error=f"mcp {self._server}.{self._tool}: timeout after {self._timeout}s")
        except Exception as e:
            return ToolResult(status="error", tool_name=self.name(),
                              error=f"mcp {self._server}.{self._tool}: {type(e).__name__}: {e}")

    async def _async_call(self, kwargs: dict) -> str:
        """（无池兜底路径——按次连接；测试/旧调用兼容）。"""
        params = StdioServerParameters(
            command=self._config.command,
            args=list(self._config.args or []), env=_env_for(self._config))
        async with stdio_client(params) as (read, write), \
                ClientSession(read, write) as session:
            await session.initialize()
            r = await session.call_tool(self._tool, kwargs)
            parts = []
            for c in r.content:
                if hasattr(c, "text"):
                    parts.append(c.text)
                else:
                    parts.append(str(c))
            return "\n".join(parts)


async def load_mcp_tools(configs: list, pool: "McpConnectionPool | None" = None) -> list:
    """加载多个 MCP server 的工具列表（探测连接，读完后释放）。

    A5 修复（2026-09-07 审查）：逐 server 降级——单 server 启动/握手失败
    仅跳过该 server（警告留痕），不拖垮引擎（坏工具不坏引擎——最小原则）。
    E1：adapter 携带池引用（有池 → 执行走常驻连接复用）。
    """
    tools = []
    for cfg in configs:
        try:
            server_tools = await _load_one(cfg, pool)
            tools.extend(server_tools)
        except Exception as e:
            logger.warning("跳过 server %s: %s: %s", cfg.name, type(e).__name__, e)
    return tools


async def _load_one(cfg, pool=None) -> list:
    """单 server 装载（失败上抛——由 load_mcp_tools 降级）。"""
    async with _open_stream(cfg) as entered:
        read, write = _unpack_stream(entered)
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()
            return [McpToolAdapter(
                server_name=cfg.name, tool_name=t.name,
                description=t.description or "",
                input_schema=t.inputSchema or {},
                config=cfg, pool=pool)
                for t in result.tools]
