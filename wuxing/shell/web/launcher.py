"""壳入口（壳 P1 · B5）——`serve`（常驻服务）/ `app`（pywebview 薄壳）。

设计 §2（双进程）：
  - **serve**：启动 HTTP+SSE+EngineManager 常驻；端口已有健康实例 → 复用提示；
  - **app**：探活 → 无则**拉起独立服务进程**（关窗不杀服务）→ pywebview 打开
    同一 URL；pywebview 缺失 → 提示浏览器 URL 回退（不阻塞）。
"""
import json
import pathlib
import subprocess
import sys
import time
import urllib.request

from wuxing.config_contract import effective_config
from wuxing.shell.web.api import register_api
from wuxing.shell.web.auth import AuthGuard, is_loopback_host, resolve_shell_token
from wuxing.shell.web.hub import EventHub
from wuxing.shell.web.manager import EngineManager
from wuxing.shell.web.server import DEFAULT_HOST, ShellServer
from wuxing.shell.web.state import RecycleStore

DEFAULT_PORT = 8723
STATIC_DIR = pathlib.Path(__file__).parent / "static"


def default_state_path() -> pathlib.Path:
    """服务侧自有状态（工作区列表）——与引擎配置面隔离。"""
    return pathlib.Path.home() / ".wuxing" / "shell" / "workspaces.json"


def probe(host: str, port: int, timeout: float = 1.5):
    """健康探活：返回 /health JSON；无实例/非本服务 → None。"""
    url = f"http://{host}:{port}/health"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        # 健康探测失败（服务未起/超时/非法响应）→ None（调用方按未就绪处理）
        return None
    if data.get("status") == "ok" and "version" in data:
        return data
    return None


def build_service(port: int = DEFAULT_PORT, host: str = DEFAULT_HOST,
                  state_path_override=None, auth_token: str | None = None,
                  allow_hosts=None, allow_origins=None):
    """构造服务（不启动）→ (manager, server)。

    远程档（O5）：auth_token 非空 → 装配 AuthGuard（guard 存在即强制）；
    allow_hosts/allow_origins 为来源白名单扩展（默认空 = 仅环回，行为不变）。
    """
    base_dir = (pathlib.Path(state_path_override).parent
                if state_path_override else default_state_path().parent)
    hub = EventHub(journal_path=base_dir / "events.jsonl")
    mgr = EngineManager(hub=hub,
                        state_path=state_path_override or default_state_path())
    guard = AuthGuard(auth_token) if auth_token else None
    srv = ShellServer(host=host, port=port, hub=hub, static_dir=STATIC_DIR,
                      auth=guard, allow_hosts=allow_hosts,
                      allow_origins=allow_origins)
    recycle = RecycleStore(base_dir / "recycle.json")
    register_api(srv, mgr, recycle=recycle)
    return mgr, srv


def ensure_service(port: int = DEFAULT_PORT, host: str = DEFAULT_HOST,
                   state_path_override=None):
    """确保服务可用：已有健康实例 → (None, None)；否则启动 → (mgr, srv)。"""
    if probe(host, port) is not None:
        return None, None
    mgr, srv = build_service(port=port, host=host,
                             state_path_override=state_path_override)
    srv.start()
    return mgr, srv


def launch_service_process(port: int = DEFAULT_PORT):
    """拉起**独立**服务进程（关窗不杀服务——设计 §2）。"""
    cmd = [sys.executable, "-m", "wuxing.cli", "shell", "serve",
           "--port", str(port)]
    kwargs = {}
    if sys.platform == "win32":
        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP（脱离控制台随父进程退出）
        kwargs["creationflags"] = 0x00000008 | 0x00000200
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, **kwargs)


def _wait_health(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                 timeout: float = 20.0, interval: float = 0.2) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if probe(host, port) is not None:
            return True
        time.sleep(interval)
    return False


def remote_auth_token(host: str) -> str | None:
    """非环回绑定所需的 token；环回 → None（不强制鉴权）。"""
    if is_loopback_host(host):
        return None
    return resolve_shell_token()


def run_serve(port: int = DEFAULT_PORT, host: str | None = None) -> int:
    """serve：启动服务并阻塞（Ctrl+C 退出）。

    远程档（O5）：非环回绑定必须能解析到 token（fail-closed——无则拒绝启动）。
    """
    host = host or DEFAULT_HOST
    existing = probe(host, port)
    if existing is not None:
        print(f"[shell] 已有服务在运行：http://{host}:{port}"
              f"（epoch={existing.get('epoch')}）")
        return 0
    token = remote_auth_token(host)
    if not is_loopback_host(host) and not token:
        print("[shell] 非环回绑定需要访问令牌（fail-closed，拒绝启动）")
        print("        设置途径：环境变量 WUXING_SHELL_TOKEN，"
              "或在凭据存储写入同名条目")
        return 2
    values = effective_config()["values"]
    mgr, srv = build_service(
        port=port, host=host, auth_token=token,
        allow_hosts=list(values.get("shell_allow_hosts") or []),
        allow_origins=list(values.get("shell_allow_origins") or []))
    srv.start()
    mode = "远程模式·鉴权已启用" if token else "仅本机"
    print(f"[shell] 服务已启动：{srv.url}（{mode}；Ctrl+C 退出）")
    if token:
        print(f"[shell] 远程入口形如 http://{host}:{port}/?token=<你的令牌>"
              "（令牌以凭据为准，不在终端打印）")
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n[shell] 停止服务")
    finally:
        srv.stop()
        mgr.shutdown()
    return 0


def run_app(port: int = DEFAULT_PORT, host: str = DEFAULT_HOST, opener=None,
            spawn=None) -> int:
    """app：薄壳——确保服务 → pywebview 打开 URL；不可用 → 浏览器回退提示。"""
    if probe(host, port) is None:
        print("[shell] 正在启动后台服务…")
        (spawn or launch_service_process)(port)
        if not _wait_health(host, port):
            print("[shell] 服务启动超时——请手动运行 `wuxing shell serve`")
            return 1
    url = f"http://{host}:{port}"
    from wuxing.shell.web import window
    open_fn = opener or window.open_window
    try:
        open_fn(url)
    except window.WindowUnavailable as exc:
        print(f"[shell] 桌面窗口不可用（{exc}）——"
              f"请用浏览器打开：{url}")
    return 0


def open_browser(url: str, opener=None) -> bool:
    """拉起系统默认浏览器（opener 可注入供测试；失败返回 False 不抛）。"""
    try:
        if opener is not None:
            return bool(opener(url))
        import webbrowser
        return bool(webbrowser.open(url))
    except Exception:
        # 无法唤起浏览器（无 GUI/无默认程序）→ False（调用方提示手动打开）
        return False


def run_web(port: int = DEFAULT_PORT, host: str = DEFAULT_HOST,
            opener=None, spawn=None) -> int:
    """web：确保服务（无则后台拉起）→ 拉起系统浏览器网页（不阻塞）。

    用户裁决 2026-09-15：默认入口只在浏览器承载；桌面应用承载由
    Electron 壳承担（pywebview 仅保留为显式 `shell app`）。
    服务为后台常驻进程（关窗/关终端不杀服务——设计 §2）。
    """
    started = False
    if probe(host, port) is None:
        print("[shell] 正在启动后台服务…")
        (spawn or launch_service_process)(port)
        if not _wait_health(host, port):
            print("[shell] 服务启动超时——请手动运行 `wuxing shell serve`")
            return 1
        started = True
    url = f"http://{host}:{port}"
    opened = open_browser(url, opener)
    print(f"[shell] 服务{'已后台启动' if started else '已在运行'}：{url}")
    if opened:
        print("[shell] 已在默认浏览器打开（服务保持后台运行）")
    else:
        print("[shell] 未能自动打开浏览器——请手动访问上述地址")
    return 0

