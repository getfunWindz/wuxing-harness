"""内置浏览器控制通道 · Python 客户端（O2-2 P1）。

协议（与 `apps/shell/desktop/src/browser-protocol.ts` 对拍——改一处必须改两处）：
  POST {endpoint}/cmd   JSON `{"cmd": ..., "args": {...}}`
  Header: `Authorization: Bearer <token>`
  响应：`{"ok": true, "data": {...}}` | `{"ok": false, "error": {"code","message"}}`
  命令白名单：status | open | snapshot | click | type | wait | evaluate | screenshot | close
  | identity_clear | views

端点解析：env（`WUXING_BROWSER_ENDPOINT` / `WUXING_BROWSER_TOKEN`）→ 文件兜底
`~/.wuxing/browser_channel.json`（桌面壳写，0600；服务复用场景无 env 时可用）。

协议版本：4（O2-2 §11.5-③——mode 第三值 storage-state + identity state_path；使用前版本门 fail-closed）。
"""
import json
import os
import pathlib
import urllib.error
import urllib.request
from typing import Protocol, runtime_checkable

PROTOCOL_VERSION = "4"
COMMANDS = ("status", "open", "snapshot", "click", "type", "wait",
            "evaluate", "screenshot", "close", "identity_clear", "views")


@runtime_checkable
class BrowserBackend(Protocol):
    """浏览器后端命令面（O2-2 P3 · MCP 缝）——形态 B（MCP 客户端后端）接入点。

    当前实现 = 回环控制通道客户端（`ChannelClient`：Electron WebContentsView
    +CDP）。未来外部 browser MCP 客户端后端实现同一 `call` 命令语义（命令集见
    `COMMANDS`；与 TS 主机逐字对拍，见 `test_browser_backend_seam.py`）即可
    替换——工具面/护栏/确认链不变。
    """

    def call(self, cmd: str, timeout: float | None = None, **args) -> dict: ...


class BrowserChannelError(RuntimeError):
    """控制通道错误（错误前缀 `browser-channel:` 统一归因）。"""

    def __init__(self, code: str, message: str):
        super().__init__(f"browser-channel: {code}: {message}")
        self.code = str(code)
        self.message = str(message)


def channel_file_path() -> pathlib.Path:
    return pathlib.Path.home() / ".wuxing" / "browser_channel.json"


def resolve_channel() -> tuple | None:
    """(endpoint, token) | None——env 优先，文件兜底。"""
    endpoint = os.environ.get("WUXING_BROWSER_ENDPOINT", "").strip()
    token = os.environ.get("WUXING_BROWSER_TOKEN", "").strip()
    if endpoint and token:
        return endpoint, token
    try:
        data = json.loads(channel_file_path().read_text(encoding="utf-8"))
        e = str(data.get("endpoint") or "").strip()
        t = str(data.get("token") or "").strip()
        if e and t:
            return e, t
    except (OSError, json.JSONDecodeError, AttributeError):
        # 无通道文件/内容损坏 → 视为未提供通道（调用侧 loud 降级）
        pass
    return None


class ChannelClient:
    """控制通道客户端（urllib；超时/错误归一；协议版本门 fail-closed）。"""

    def __init__(self, endpoint: str, token: str, timeout: float = 30.0):
        self.endpoint = str(endpoint).rstrip("/")
        self.token = str(token)
        self.timeout = float(timeout)
        self._protocol_ok = False

    @classmethod
    def from_env(cls, timeout: float = 30.0):
        resolved = resolve_channel()
        if resolved is None:
            return None
        return cls(resolved[0], resolved[1], timeout=timeout)

    def _post(self, cmd: str, args: dict, timeout: float | None) -> dict:
        body = json.dumps({"cmd": cmd, "args": args}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.endpoint}/cmd", data=body, method="POST",
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.token}"})
        try:
            with urllib.request.urlopen(
                    req, timeout=timeout or self.timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            try:
                payload = json.loads(exc.read().decode("utf-8", "replace"))
            except Exception as inner:
                raise BrowserChannelError(
                    "http-error", f"HTTP {exc.code}") from inner
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise BrowserChannelError(
                "unreachable", f"控制通道不可达：{exc}") from exc
        if not isinstance(payload, dict) or not payload.get("ok"):
            err = (payload or {}).get("error") or {}
            raise BrowserChannelError(
                str(err.get("code") or "bad-response"),
                str(err.get("message") or payload))
        data = payload.get("data")
        return dict(data) if isinstance(data, dict) else {}

    def status(self) -> dict:
        """握手：{protocol, app, electron, ...}（不走版本门）。"""
        return self._post("status", {}, None)

    def _ensure_protocol(self) -> None:
        """使用前校验控制通道协议 ≥4（旧通道 loud 拒结——防静默丢身份/视图目标/登录态）。"""
        if self._protocol_ok:
            return
        data = self.status()
        proto = str(data.get("protocol") or "").strip()
        try:
            major = int(proto)
        except ValueError:
            major = 0
        if major < 4:
            raise BrowserChannelError(
                "protocol-mismatch",
                f"控制通道版本过旧（{proto or '?'} < 4）——请重启桌面壳后再试")
        self._protocol_ok = True

    def call(self, cmd: str, timeout: float | None = None, **args) -> dict:
        if cmd not in COMMANDS:
            raise BrowserChannelError("unknown-command", f"未知命令：{cmd}")
        if cmd != "status":
            self._ensure_protocol()
        return self._post(cmd, args, timeout)
