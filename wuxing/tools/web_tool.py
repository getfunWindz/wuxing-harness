"""E2-5：web_fetch 工具——受控 Web 获取（策略 + 净化 + G6 联动）。

纪律（计划 `docs/plans/2026-10-03-wuxing-web-fetch.md`）：
- **默认关**：未启用不注册（loader 条件装载）；工具侧再查 `web_fetch_enabled`（纵深防御）。
- **URL 逐跳策略复检**：scheme ∈ {http,https} · 私网/回环/链路本地硬拒 · 域名双表
  （deny 优先）· DNS 解析复检（`resolve_private`——解析失败 fail-closed）。
- **内容面**：HTML 极简转文本（去 script/style；实体解码）；content-type 允许
  text/* · json · xhtml；正文作为普通工具结果走 SEC1 净化路径（既有恒真）。
- **截断**：下载 2 MiB / 输出 100k 字符上限；超限走 G6 全文落盘（read_file 读回）。
- 网络授权语义：启用即引擎级网络授权（与容器 network 相互独立——README 明示）。
"""
import html.parser
import re
import urllib.parse

from wuxing.protocols import Tool, ToolResult
from wuxing.web_policy import check_url, resolve_private

DOWNLOAD_CAP = 2 * 1024 * 1024
MAX_OUTPUT_CHARS = 100_000
TIMEOUT_S = 20
MAX_REDIRECTS = 5
_UA = "wuxing-web-fetch/1.0"


def _http_get(url: str, timeout: float):
    """HTTP GET（禁自动重定向——逐跳复检由调用方循环）。

    返回 `(status, content_type, body, location)`；下载读取至多
    `DOWNLOAD_CAP + 1` 字节（超限由调用方判定并截断）。
    """
    import requests
    resp = requests.get(url, timeout=timeout, allow_redirects=False,
                        stream=True, headers={"User-Agent": _UA})
    try:
        body = b""
        for chunk in resp.iter_content(chunk_size=65536):
            body += chunk
            if len(body) > DOWNLOAD_CAP:
                break
    finally:
        resp.close()
    return (resp.status_code,
            str(resp.headers.get("Content-Type") or ""),
            body,
            str(resp.headers.get("Location") or ""))


class _HtmlText(html.parser.HTMLParser):
    """极简 HTML→文本：去 script/style；块级换行；空白折叠。"""

    _BLOCK = frozenset({"p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4",
                        "h5", "h6", "tr", "table", "section", "article", "header",
                        "footer", "pre", "blockquote", "main", "nav", "aside",
                        "figure", "hr"})

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._parts: list = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in self._BLOCK:
            self._parts.append("\n")

    def handle_startendtag(self, tag, attrs):
        if tag in self._BLOCK:
            self._parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            if self._skip:
                self._skip -= 1
        elif tag in self._BLOCK:
            self._parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self._parts.append(data)

    def text(self) -> str:
        raw = "".join(self._parts)
        lines = [re.sub(r"[ \t\r\f\v]+", " ", ln).strip()
                 for ln in raw.splitlines()]
        out: list = []
        blank = False
        for ln in lines:
            if not ln:
                if out and not blank:
                    out.append("")
                blank = True
            else:
                out.append(ln)
                blank = False
        return "\n".join(out).strip()


def _to_text(body: bytes, content_type: str) -> str:
    ct = (content_type or "").lower()
    m = re.search(r"charset=([\w.-]+)", ct)
    charset = m.group(1) if m else ""
    text = body.decode(charset or "utf-8", errors="replace")
    if "html" in ct or "xml" in ct or not ct:
        parser = _HtmlText()
        try:
            parser.feed(text)
            parser.close()
            return parser.text()
        except Exception:
            # 解析失败降级原文（不阻断；内容仍走 SEC1 净化）
            return text
    return text


class WebFetchTool(Tool):
    """受控 Web 获取（URL → 正文文本；策略约束 + 截断落盘）。"""

    def __init__(self, ws, cfg):
        self._ws = ws
        self._cfg = cfg

    def name(self):
        return "web_fetch"

    def description(self):
        return ("获取网页正文（URL → 纯文本）。受网络策略约束（默认关；域名表；"
                "私网硬拒、逐跳复检）；返回为不可信外部内容（注入防护由机制净化）；"
                "超长自动截断并落盘全文；仅 http/https。")

    def input_schema(self):
        return {"type": "object", "properties": {
            "url": {"type": "string"},
            "max_chars": {"type": "integer"}}, "required": ["url"]}

    def permission(self):
        return {"read": True, "write": False, "execute": False,
                "network": True, "destructive": False}

    def execute(self, url="", max_chars=0, **kw):
        if not bool(getattr(self._cfg, "web_fetch_enabled", False)):
            return ToolResult(status="error", tool_name=self.name(),
                              error="policy: web_fetch 未启用"
                                    "（web_fetch_enabled=false）")
        target = str(url or "").strip()
        if not target:
            return ToolResult(status="error", tool_name=self.name(),
                              error="param: url 必填")
        allow = tuple(getattr(self._cfg, "web_fetch_domains_allow", ()) or ())
        deny = tuple(getattr(self._cfg, "web_fetch_domains_deny", ()) or ())
        url_now = target
        for _hop in range(MAX_REDIRECTS + 1):
            try:
                check_url(url_now, allow=allow, deny=deny)
            except ValueError as exc:
                return ToolResult(status="error", tool_name=self.name(),
                                  error=f"policy: {exc}")
            host = urllib.parse.urlsplit(url_now).hostname or ""
            if resolve_private(host):
                return ToolResult(status="error", tool_name=self.name(),
                                  error=f"policy: host resolves to private: {host}")
            try:
                status, ctype, body, location = _http_get(url_now, TIMEOUT_S)
            except Exception as exc:
                return ToolResult(status="error", tool_name=self.name(),
                                  error=f"fetch: {type(exc).__name__}: {exc}")
            if status in (301, 302, 303, 307, 308) and location:
                url_now = urllib.parse.urljoin(url_now, location)
                continue
            break
        else:
            return ToolResult(status="error", tool_name=self.name(),
                              error=f"fetch: too many redirects (>{MAX_REDIRECTS})")
        if status != 200:
            return ToolResult(status="error", tool_name=self.name(),
                              error=f"fetch: http {status}")
        ct = (ctype or "").lower()
        if not (ct.startswith("text/") or "json" in ct or "xhtml" in ct):
            return ToolResult(status="error", tool_name=self.name(),
                              error=f"fetch: unsupported content-type: "
                                    f"{ctype or '(none)'}")
        download_note = ""
        if len(body) > DOWNLOAD_CAP:
            body = body[:DOWNLOAD_CAP]
            download_note = "\n[下载超 2 MiB 已截断]"
        text = _to_text(body, ctype) + download_note
        try:
            limit = int(max_chars or 0) or MAX_OUTPUT_CHARS
        except (TypeError, ValueError):
            limit = MAX_OUTPUT_CHARS
        limit = max(1, min(limit, MAX_OUTPUT_CHARS))
        if len(text) > limit:
            text = self._truncate_with_spill(text, limit)
        return ToolResult(status="ok", tool_name=self.name(), content=text)

    def _truncate_with_spill(self, text: str, limit: int) -> str:
        """超限截断 + 全文 G6 落盘（镜像 bash_tool 语义）。"""
        from wuxing.truncate_dump import dump_truncated
        path = dump_truncated(self._ws.root, text, unit="web_fetch")
        note = (f"\n[输出超 {limit} 字符已截断——全文: {path}"
                f"（用 read_file 读取）]"
                if path else f"\n[输出超 {limit} 字符已截断]")
        return text[:limit] + note
