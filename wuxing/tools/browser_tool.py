"""内置浏览器三工具（O2-2 P1）：browser_navigate / browser_snapshot / browser_screenshot。

职责边界：
  - 授权：非回环 = scheme + 域名双表（deny 优先）+ 私网/链路本地硬拒（含 DNS 复检）；
    回环 = 动态授权（browser_guard：占用探测→确认门→自进化条目）；
  - 通道：Electron 控制通道（browser_channel）；web 模式 loud 降级（绝不静默回退）；
  - 落盘：快照/evaluate 全文与截图默认按 run 分目录（.wuxing/browser/<run>/；
    §11.5-② D5——截图可显式指定工作区内路径供用户复核）；
  - 描述文案明示「浏览器自动化≠安全边界」。
"""
import ipaddress
import logging
import os
import pathlib
import shutil
import time
import urllib.parse

from wuxing import browser_guard
from wuxing.browser_channel import BrowserChannelError, ChannelClient
from wuxing.browser_identity import identity_for
from wuxing.protocols import Tool, ToolResult
from wuxing.web_policy import host_allowed, is_private_host
from wuxing.web_policy import resolve_private as _policy_resolve_private

MAX_SNAPSHOT_CHARS = 8000
logger = logging.getLogger(__name__)


def _default_client():
    return ChannelClient.from_env()


def _loopback_host(host: str) -> bool:
    h = str(host or "").strip().lower().rstrip(".")
    if h == "localhost" or h.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        # 非 IP 字面量（域名等）→ 走非回环分支
        return False


class _BrowserToolBase(Tool):
    def __init__(self, ws, cfg=None, client=None, trace_getter=None,
                 binding=None):
        self.ws = ws
        self.cfg = cfg
        self._client = client
        self._trace_getter = trace_getter
        # §11.5-②（Q1=B/D5）：会话绑定与 run 落盘域（引擎装配注入；缺省=零变化）
        self._binding = dict(binding or {})

    def _channel(self):
        return self._client if self._client is not None else _default_client()

    def _identity(self):
        """命令携带的浏览器身份（§11.5-②：基键+会话 overlay；anchor 取真实工作区）。"""
        return identity_for(self.cfg, self.ws,
                            session=self._binding.get("session", ""))

    def _identity_checked(self):
        """身份 + storage-state 档可用性（§11.5-③ D7：非法状态 loud 拒，不回退档位）。"""
        ident = self._identity()
        err = str(ident.get("state_error") or "")
        if err:
            return ident, f"storage-state 档不可用（fail-closed）：{err}"
        return ident, None

    def _scope(self) -> str:
        """落盘域：run 短码（缺省 default——headless/测试零变化）。"""
        return str(self._binding.get("run") or "default")

    def _err(self, message: str) -> ToolResult:
        return ToolResult(status="error", tool_name=self.name(), error=message)

    def _no_channel_error(self) -> ToolResult:
        return self._err(
            "内置浏览器仅桌面壳可用（当前为 web 承载）——"
            "请在 Electron 桌面壳中运行后重试")

    def _perm_execute(self) -> dict:
        return {"read": True, "write": False, "execute": True,
                "network": True, "destructive": False}


class BrowserNavigateTool(_BrowserToolBase):
    """打开 URL（含回环动态授权；可能挂起待用户确认）。"""

    def __init__(self, ws, cfg, client=None, guard_check=None,
                 resolve_private=None, store_path=None, trace_getter=None,
                 binding=None, lan_check=None, resolve_addrs=None):
        super().__init__(ws, cfg, client=client, trace_getter=trace_getter,
                         binding=binding)
        self._guard = guard_check or browser_guard.check_loopback
        self._resolve_private = resolve_private or _policy_resolve_private
        self._store_path = store_path
        # §11.5-③：LAN 动态授权（可注入——离线可测）
        self._lan_check = lan_check or browser_guard.check_lan
        self._resolve_addrs = resolve_addrs or browser_guard.resolve_addrs

    def name(self) -> str:
        return "browser_navigate"

    def description(self) -> str:
        return ("在内置浏览器（仅桌面壳）打开 URL。回环地址（localhost/127.0.0.1）"
                "走动态授权：先探测占用——无监听明确失败；有监听且未批准过则弹确认"
                "（允许后记录条目，换程序/换端口会重新确认）。局域网地址"
                "（RFC1918/ULA）必须先在 browser_lan_allow 配置 CIDR 白名单，"
                "首访逐地址确认。公网需显式列入"
                "browser_domains_allow；私网/链路本地硬拒。"
                "用途限核查/调试自有页面——不得用于代注册/代支付/破解验证码等操作。"
                "备注：浏览器自动化≠安全边界。")

    def input_schema(self) -> dict:
        return {"type": "object", "properties": {
            "url": {"type": "string", "description": "http/https URL"},
            "reason": {"type": "string",
                       "description": "访问用途（会展示给用户，标注为 AI 提供）"}},
            "required": ["url"]}

    def permission(self) -> dict:
        return self._perm_execute()

    def execute(self, url="", reason="", **kw) -> ToolResult:
        target = str(url or "").strip()
        parsed = urllib.parse.urlsplit(target)
        scheme = (parsed.scheme or "").lower()
        if scheme not in ("http", "https"):
            return self._err(f"仅支持 http/https：{target or '(empty)'}")
        host = (parsed.hostname or "").strip()
        if not host:
            return self._err(f"URL 缺少主机名：{target}")
        try:
            port = parsed.port or (443 if scheme == "https" else 80)
        except ValueError:
            return self._err(f"URL 端口非法：{target}")
        reason_text = str(reason or "")
        if _loopback_host(host):
            decision = self._guard(host, port, reason=reason_text,
                                   store_path=self._store_path)
            if decision.kind == "no_listener":
                return self._err(
                    f"该地址无应用监听：{decision.address}——"
                    "请先启动本地服务（如 npm run dev）再访问")
            if decision.kind == "confirm_required":
                payload = browser_guard.confirm_payload(
                    decision, agent_reason=reason_text)
                return ToolResult(
                    status="needs_answer", tool_name=self.name(),
                    content=f"[browser] 回环访问待确认：{decision.address}",
                    pending_questions=[payload],
                    pending_meta={"kind": "browser_access",
                                  "pending_id": decision.pending_id,
                                  "address": decision.address,
                                  "guard_kind": "loopback"})
        else:
            # §11.5-③（Q1=A/D2）：私网字面量，或已配置 LAN 白名单时名称解析落私网
            # → LAN 路径（CIDR 白名单 + 逐地址确认）；否则既有公网路径不变。
            lan_allow = list(getattr(self.cfg, "browser_lan_allow", None) or ())
            if is_private_host(host) or (lan_allow
                                         and self._resolve_private(host)):
                decision = self._lan_check(
                    host, port, lan_allow=lan_allow, reason=reason_text,
                    store_path=self._store_path)
                if decision.kind == "lan_denied":
                    return self._err(f"私网/LAN 访问被拒：{decision.note}")
                if decision.kind == "no_listener":
                    return self._err(
                        f"该地址无应用监听：{decision.address}——"
                        "请先启动服务或确认设备在线")
                if decision.kind == "confirm_required":
                    payload = browser_guard.confirm_payload(
                        decision, agent_reason=reason_text)
                    return ToolResult(
                        status="needs_answer", tool_name=self.name(),
                        content=f"[browser] 局域网访问待确认：{decision.address}",
                        pending_questions=[payload],
                        pending_meta={"kind": "browser_access",
                                      "pending_id": decision.pending_id,
                                      "address": decision.address,
                                      "guard_kind": "lan"})
                # allowed → 落通道
            else:
                allow = list(self.cfg.browser_domains_allow or ())
                if not allow:
                    # 设计 §3.1：公网须显式列入 allow（默认拒——与 web_fetch 语义不同）
                    return self._err(
                        f"domain not allowed: {host}（未配置 browser_domains_allow——默认拒）")
                if not host_allowed(host, allow=allow,
                                    deny=self.cfg.browser_domains_deny):
                    return self._err(f"domain not allowed: {host}")
                if self._resolve_private(host):
                    return self._err(
                        f"私网/链路本地硬拒：{host}（DNS 复检命中私网/fail-closed）")
        ident, ident_err = self._identity_checked()
        if ident_err:
            return self._err(ident_err)
        client = self._channel()
        if client is None:
            return self._no_channel_error()
        try:
            data = client.call("open", url=target, identity=ident)
        except BrowserChannelError as exc:
            return self._err(str(exc))
        _ident = data.get("identity")
        if isinstance(_ident, dict):
            _tr = self._trace_getter() if self._trace_getter else None
            if _tr is not None:
                try:
                    _tr.log("browser_identity_used", "", "",
                            key=str(_ident.get("key") or ""),
                            mode=str(_ident.get("mode") or ""),
                            state=str(_ident.get("state") or "reused"))
                except Exception as exc:
                    logger.debug("身份审计事件记录失败：%s", exc)
        if ident.get("mode") == "storage-state":
            # §11.5-③ D10：登录态加载审计（只记计数/路径短码——值纪律）
            _tr = self._trace_getter() if self._trace_getter else None
            if _tr is not None:
                counts = data.get("storage_state") or {}
                _path = str(ident.get("state_path") or "")
                try:
                    import hashlib as _hashlib
                    _tr.log("browser_storage_state_loaded", "", "",
                            key=str(ident.get("key") or ""),
                            path_token=_hashlib.sha1(
                                _path.encode()).hexdigest()[:8],
                            cookies=int(counts.get("cookies") or 0),
                            origins=int(counts.get("origins") or 0))
                except Exception as exc:
                    logger.debug("storage-state 审计事件记录失败：%s", exc)
        title = str(data.get("title") or "").strip() or "(无标题)"
        final = str(data.get("url") or target)
        return ToolResult(
            status="ok", tool_name=self.name(),
            content=f"已打开：{title}｜{final}（用 browser_snapshot 读取页面元素）")


class BrowserSnapshotTool(_BrowserToolBase):
    """读取页面无障碍树快照（行式；超长截断 + 全文落盘）。"""

    def name(self) -> str:
        return "browser_snapshot"

    def description(self) -> str:
        return ("读取内置浏览器当前页面的无障碍树快照"
                "（行式：`- role \"name\" [ref=eN]`）；交互元素带 ref。"
                "超长自动截断（全文落盘留档）。先用 browser_navigate 打开页面。")

    def input_schema(self) -> dict:
        return {"type": "object", "properties": {}}

    def permission(self) -> dict:
        return self._perm_execute()

    def execute(self, **kw) -> ToolResult:
        client = self._channel()
        if client is None:
            return self._no_channel_error()
        ident, ident_err = self._identity_checked()
        if ident_err:
            return self._err(ident_err)
        try:
            data = client.call("snapshot", identity=ident)
        except BrowserChannelError as exc:
            return self._err(str(exc))
        text = str(data.get("snapshot") or "")
        note = ""
        if len(text) > MAX_SNAPSHOT_CHARS:
            rel = self._persist_full(text)
            text = text[:MAX_SNAPSHOT_CHARS]
            note = f"\n…（快照超长已截断；全文落盘：{rel}）"
        meta = f"refs={data.get('refs', 0)}"
        if data.get("truncated"):
            meta += "；树级截断=true"
        return ToolResult(status="ok", tool_name=self.name(),
                          content=f"{text}{note}\n（{meta}）")

    def _persist_full(self, text: str) -> str:
        rel_dir = (pathlib.Path(".wuxing") / "browser" / self._scope()
                   / "snapshots")
        name = f"snapshot-{time.strftime('%Y%m%d-%H%M%S')}.txt"
        target = self.ws.root / rel_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        return (rel_dir / name).as_posix()


class BrowserScreenshotTool(_BrowserToolBase):
    """页面截图（PNG 落工作区；供用户复核，不做模型视觉理解）。"""

    def name(self) -> str:
        return "browser_screenshot"

    def description(self) -> str:
        return ("截取内置浏览器当前页面为 PNG 并保存到工作区"
                "（默认 `.wuxing/browser/<run>/screenshots/`——内部留档；"
                "可显式指定工作区内相对路径用于用户复核）。模型不做视觉理解——"
                "请配合 browser_snapshot 的文本快照做判断。")

    def input_schema(self) -> dict:
        return {"type": "object", "properties": {
            "path": {"type": "string",
                     "description": "工作区内相对路径（可选，默认"
                                    " `.wuxing/browser/<run>/screenshots/`）"},
            "full_page": {"type": "boolean", "description": "整页截图（默认否）"}}}

    def permission(self) -> dict:
        return {"read": True, "write": True, "execute": True,
                "network": True, "destructive": False}

    def execute(self, path="", full_page=False, **kw) -> ToolResult:
        raw = str(path or "").strip()
        if raw:
            rel_path = pathlib.PurePosixPath(raw.replace("\\", "/"))
            if rel_path.is_absolute() or ".." in rel_path.parts:
                return self._err(f"截图路径必须在工作区内（相对路径）：{raw}")
        else:
            rel_path = pathlib.PurePosixPath(
                ".wuxing", "browser", self._scope(), "screenshots",
                f"shot-{time.strftime('%Y%m%d-%H%M%S')}.png")
        client = self._channel()
        if client is None:
            return self._no_channel_error()
        ident, ident_err = self._identity_checked()
        if ident_err:
            return self._err(ident_err)
        try:
            data = client.call("screenshot", full_page=bool(full_page),
                               identity=ident)
        except BrowserChannelError as exc:
            return self._err(str(exc))
        tmp = str(data.get("path") or "")
        if not tmp or not pathlib.Path(tmp).exists():
            return self._err(f"截图为空或临时文件缺失：{tmp or '(empty)'}")
        dest = self.ws.root / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(tmp, dest)
        try:
            os.remove(tmp)
        except OSError:
            # 临时文件清理失败不阻塞交付（Electron 侧退出兜底清理）
            pass
        return ToolResult(
            status="ok", tool_name=self.name(),
            content=f"截图已保存：{rel_path.as_posix()}（供用户复核；模型不做视觉理解）")


# ---- O2-2 P2：操作面（click/type/wait） ----


def _validate_target(ref, selector) -> str:
    """ref|selector 恰一（空白视缺）——返回错误文案（空串=合法）。"""
    r = str(ref or "").strip()
    s = str(selector or "").strip()
    if r == "" and s == "":
        return "需要 ref 或 selector（恰一）"
    if r != "" and s != "":
        return "ref 与 selector 不能同时提供（恰一）"
    return ""


def _target_args(ref, selector) -> dict:
    r = str(ref or "").strip()
    return {"ref": r} if r != "" else {"selector": str(selector or "").strip()}


class BrowserClickTool(_BrowserToolBase):
    """点击页面元素（ref 来自最近快照；真实鼠标 isTrusted）。"""

    def name(self) -> str:
        return "browser_click"

    def description(self) -> str:
        return ("点击内置浏览器页面元素（真实鼠标事件）。ref 来自最近一次"
                "browser_snapshot；**快照换代后旧 ref 失效**（报错提示重新取快照）。"
                "点击后请重新取快照查看页面变化。")

    def input_schema(self) -> dict:
        return {"type": "object", "properties": {
            "ref": {"type": "string", "description": "快照中的元素 ref（如 e3）"},
            "selector": {"type": "string",
                         "description": "CSS selector（与 ref 二选一）"}}}

    def permission(self) -> dict:
        return self._perm_execute()

    def execute(self, ref="", selector="", **kw) -> ToolResult:
        err = _validate_target(ref, selector)
        if err:
            return self._err(err)
        client = self._channel()
        if client is None:
            return self._no_channel_error()
        args = _target_args(ref, selector)
        ident, ident_err = self._identity_checked()
        if ident_err:
            return self._err(ident_err)
        try:
            data = client.call("click", identity=ident, **args)
        except BrowserChannelError as exc:
            return self._err(str(exc))
        by = str(data.get("by") or args.get("ref") or args.get("selector") or "")
        return ToolResult(status="ok", tool_name=self.name(),
                          content=f"已点击 {by}；请重新取快照查看页面变化")


class BrowserTypeTool(_BrowserToolBase):
    """在页面元素中输入文本（真实聚焦+输入；submit 追加回车）。"""

    def name(self) -> str:
        return "browser_type"

    def description(self) -> str:
        return ("在内置浏览器页面元素（ref/selector）中输入文本（真实聚焦 + "
                "文本输入）；submit=true 时追加回车提交。ref 来自最近快照，"
                "换代后失效。输入后请重新取快照查看结果。")

    def input_schema(self) -> dict:
        return {"type": "object", "properties": {
            "ref": {"type": "string", "description": "快照中的元素 ref"},
            "selector": {"type": "string",
                         "description": "CSS selector（与 ref 二选一）"},
            "text": {"type": "string",
                     "description": "要输入的文本（可为空仅当 submit=true）"},
            "submit": {"type": "boolean",
                       "description": "输入后按回车提交（默认否）"}}}

    def permission(self) -> dict:
        return self._perm_execute()

    def execute(self, ref="", selector="", text=None, submit=False,
                **kw) -> ToolResult:
        if not isinstance(text, str):
            return self._err("type 需要 text 字符串")
        if not isinstance(submit, bool):
            return self._err("submit 必须是布尔")
        err = _validate_target(ref, selector)
        if err:
            return self._err(err)
        if text == "" and not submit:
            return self._err("text 为空时需 submit=true（否则无意义）")
        client = self._channel()
        if client is None:
            return self._no_channel_error()
        args = {**_target_args(ref, selector), "text": text, "submit": submit}
        ident, ident_err = self._identity_checked()
        if ident_err:
            return self._err(ident_err)
        try:
            data = client.call("type", identity=ident, **args)
        except BrowserChannelError as exc:
            return self._err(str(exc))
        by = str(data.get("by") or args.get("ref") or args.get("selector") or "")
        return ToolResult(status="ok", tool_name=self.name(),
                          content=f"已输入 {by}（{len(text)} 字符，"
                                  f"submit={submit}）；请重新取快照查看结果")


class BrowserWaitTool(_BrowserToolBase):
    """等待页面条件（selector/文本出现或固定毫秒）。"""

    def name(self) -> str:
        return "browser_wait"

    def description(self) -> str:
        return ("等待内置浏览器页面条件：selector 出现 / 文本出现（可读文本）/"
                "固定毫秒。超时返回 found=false（不报错）。selector/text 默认"
                "超时 5000ms（上限 30000）；ms 上限 60000。")

    def input_schema(self) -> dict:
        return {"type": "object", "properties": {
            "selector": {"type": "string",
                         "description": "等待出现的 CSS selector"},
            "text": {"type": "string", "description": "等待出现的文本"},
            "ms": {"type": "integer",
                   "description": "固定等待毫秒（1..60000，与 selector/text 互斥）"},
            "timeout_ms": {"type": "integer",
                           "description": "selector/text 等待上限（默认 5000，上限 30000）"}}}

    def permission(self) -> dict:
        return self._perm_execute()

    def execute(self, selector="", text="", ms=None, timeout_ms=None,
                **kw) -> ToolResult:
        s = str(selector or "").strip()
        t = str(text or "").strip()
        msv = None
        if ms is not None:
            try:
                msv = int(ms)
            except (TypeError, ValueError):
                return self._err("ms 必须是整数")
            if not (1 <= msv <= 60000):
                return self._err("ms 越界（1..60000）")
        tov = None
        if timeout_ms is not None:
            try:
                tov = int(timeout_ms)
            except (TypeError, ValueError):
                return self._err("timeout_ms 必须是整数")
            if not (1 <= tov <= 30000):
                return self._err("timeout_ms 越界（1..30000）")
        given = (1 if s else 0) + (1 if t else 0) + (1 if msv is not None else 0)
        if given != 1:
            return self._err("需要 selector/text/ms 恰一")
        client = self._channel()
        if client is None:
            return self._no_channel_error()
        args: dict = {}
        if s:
            args["selector"] = s
        if t:
            args["text"] = t
        if msv is not None:
            args["ms"] = msv
        if tov is not None:
            args["timeout_ms"] = tov
        ident, ident_err = self._identity_checked()
        if ident_err:
            return self._err(ident_err)
        try:
            data = client.call("wait", identity=ident, **args)
        except BrowserChannelError as exc:
            return self._err(str(exc))
        if data.get("found"):
            return ToolResult(
                status="ok", tool_name=self.name(),
                content=f"等待满足：mode={data.get('mode', '')}（"
                        f"elapsed_ms={data.get('elapsed_ms', 0)}）")
        note = str(data.get("note") or "")
        return ToolResult(status="ok", tool_name=self.name(),
                          content=f"等待超时（found=false）{note}")


# ---- O2-2 P3：evaluate 显式档（脚本执行面；双闸默认关） ----

EVALUATE_MAX_CHARS = 8000


class BrowserEvaluateTool(_BrowserToolBase):
    """在页面中执行 JS 表达式（显式档；固定 CDP 参数，非任意 CDP 透传）。"""

    def name(self) -> str:
        return "browser_evaluate"

    def description(self) -> str:
        return ("在内置浏览器当前页面执行 JS 表达式并返回值（**脚本执行面**："
                "仅显式开启时可用；优先用 snapshot/click/type 等结构化操作，"
                "本工具仅在确有必要时使用）。结果超长截断（全文落盘留档）。"
                "备注：浏览器自动化≠安全边界。")

    def input_schema(self) -> dict:
        return {"type": "object", "properties": {
            "expression": {"type": "string",
                           "description": "要执行的 JS 表达式（≤4000 字符）"}},
            "required": ["expression"]}

    def permission(self) -> dict:
        return self._perm_execute()

    def execute(self, expression="", **kw) -> ToolResult:
        expr = str(expression or "")
        if expr.strip() == "":
            return self._err("需要非空 expression 字符串")
        if len(expr) > 4000:
            return self._err("expression 超长（≤4000 字符）")
        client = self._channel()
        if client is None:
            return self._no_channel_error()
        ident, ident_err = self._identity_checked()
        if ident_err:
            return self._err(ident_err)
        try:
            data = client.call("evaluate", expression=expr,
                               identity=ident)
        except BrowserChannelError as exc:
            return self._err(str(exc))
        exception = str(data.get("exception") or "").strip()
        if exception:
            return self._err(f"表达式异常：{exception[:400]}")
        raw = data.get("value")
        value = "undefined" if raw is None else str(raw)
        note = ""
        if len(value) > EVALUATE_MAX_CHARS:
            rel = self._persist_full(value)
            value = value[:EVALUATE_MAX_CHARS]
            note = f"\n…（结果超长已截断；全文落盘：{rel}）"
        return ToolResult(status="ok", tool_name=self.name(),
                          content=f"{value}{note}")

    def _persist_full(self, text: str) -> str:
        rel_dir = (pathlib.Path(".wuxing") / "browser" / self._scope()
                   / "evaluates")
        name = (f"evaluate-{time.strftime('%Y%m%d-%H%M%S')}-"
                f"{time.time_ns() % 1000000:06d}.txt")
        target = self.ws.root / rel_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        return (rel_dir / name).as_posix()
