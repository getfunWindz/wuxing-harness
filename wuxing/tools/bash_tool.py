"""bash 工具（P2：执行命令，cwd=工作区）。

护栏：超时（默认 120s，可传 timeout 覆盖 clamp 1..600）+ 输出截断
（MAX_OUTPUT 字符，保留末尾——超限全文落盘 G6）+ 失败时返回 stderr 摘要。
R3-2 原生沙箱（用户裁决：剥离 Docker）：开启时——命令在工作区内执行 +
敏感环境变量剥离（白名单，大小写不敏感）；网络允许；完整性 partial（诚实上报）。
O1/O4（2026-10-07）：执行面为 POSIX shell——Windows 默认 git-bash（用户声明
主 terminal；WSL/PowerShell/cmd 可选档）；macOS 默认 zsh；Linux bash→sh
（wuxing.shells 解析；无 bash 落 cmd 回退档，可见上报）；杀树 System32 绝对
路径；stdin 非交互（DEVNULL）；PowerShell 档带 UTF-8 输出前导。
"""
import logging
import os
import pathlib
import shutil
import signal
import subprocess

from wuxing import shells
from wuxing.protocols import Tool
from wuxing.sandbox import (
    MODES,
    render_container_command,
    template_hash,
    validate_container_template,
)

logger = logging.getLogger(__name__)

MAX_OUTPUT = 20000

# PowerShell 档：UTF-8 输出编码前导（pi powershell.js / DSH ENCODING_PREAMBLE 双源参考）
_PS_UTF8_PREAMBLE = "try { [Console]::OutputEncoding=[System.Text.Encoding]::UTF8 } catch {}\n"

# O1：shell 类型 → 描述文案（route_info 同源 kind）
_SHELL_LABEL = {
    "bash": "POSIX bash（Windows 经 git-bash / macOS·Linux 原生 bash）",
    "zsh": "zsh（macOS 默认）",
    "posix": "POSIX sh",
    "powershell": "PowerShell（-NoProfile -NonInteractive + UTF-8 前导）",
    "cmd": "cmd（Windows 回退档/显式选择）",
    "wsl": "WSL（Linux VM 内 bash——工作区路径为 /mnt/… 语义）",
    "custom": "自定义 shell",
}
_SHELL_SEMANTICS = {
    "bash": "管道/引号/重定向按 POSIX shell 语义",
    "zsh": "管道/引号/重定向按 zsh（POSIX）语义",
    "posix": "管道/引号/重定向按 POSIX sh 语义",
    "powershell": "命令语法为 PowerShell（管道对象流）",
    "cmd": "命令语法为 cmd",
    "wsl": "命令在 WSL 内执行（bash 语义；宿主路径按 /mnt/… 访问）",
    "custom": "命令语义由自定义 shell 决定",
}


def _unix_tool_dirs() -> list:
    """探测 Unix 风格工具目录（git-bash 等）——PATH 注入用（Wave-1 Task B3）。

    仅探测存在目录（缺失 = 不注入；Windows 原生环境不报错）。
    """
    dirs = []
    for c in ("C:/Program Files/Git/usr/bin",
              "C:/Program Files/Git/bin",
              "C:/Program Files (x86)/Git/usr/bin"):
        if pathlib.Path(c).is_dir():
            dirs.append(c)
    which_bash = shutil.which("bash")
    if which_bash:
        p = pathlib.Path(which_bash).parent
        for cand in (p, p.parent / "usr" / "bin"):
            if cand.is_dir() and str(cand) not in dirs:
                dirs.append(str(cand))
    return dirs

# 容器运行时级失败退出码（不静默回退 native）：125-127=Docker/Podman 约定，
# 9009=部分 Windows cmd「命令未找到」
_CONTAINER_FAIL_CODES = {125, 126, 127, 9009}
# 运行时缺失/不可达的报错标记（退出码不可靠——Windows cmd 未找到返回 1；
# _decode_output 已做 GBK 回退，此处按解码后文本匹配）
_RUNTIME_FAIL_MARKERS = (
    "is not recognized as an internal or external command",  # cmd（英文）
    "不是内部或外部命令",                                      # cmd（中文）
    "command not found",                                     # POSIX sh/bash
    "cannot connect to the docker daemon",                   # docker 守护未启
    "error during connect",                                  # docker 连接失败
)


def _runtime_failure(rc: int, text: str) -> bool:
    """容器运行时级失败（启动/连接/命令缺失）——非命令自身的业务退出码。"""
    if rc in _CONTAINER_FAIL_CODES:
        return True
    low = (text or "").lower()
    return any(m in low for m in _RUNTIME_FAIL_MARKERS)

# P3 T3：env 白名单（沙箱最小版）——key/代理类变量一律剥离，防泄漏（DSH 教训）
# PYTHONHASHSEED 保留：Windows 下 Python 初始化 hash 随机化需要（且确定性有益）
_ENV_ALLOW = {"PATH", "TMP", "TEMP", "HOME", "USERPROFILE", "SystemRoot",
              "COMSPEC", "WINDIR", "HOMEDRIVE", "HOMEPATH", "PATHEXT", "OS",
              "PYTHONIOENCODING", "PYTHONHASHSEED", "LANG", "TZ"}
_ENV_ALLOW_LOWER = {k.lower() for k in _ENV_ALLOW}


def _in_env_allow(key: str) -> bool:
    """白名单匹配（大小写不敏感——O1；对齐 code_mode 修复轴）。"""
    return str(key).lower() in _ENV_ALLOW_LOWER


def _decode_output(raw) -> str:
    """G3（评测实测）：子进程输出宽容解码——UTF-8 优先、GBK 回退、最后 replace。

    Windows 默认 GBK 读取原始 UTF-8 字节会 UnicodeDecodeError 崩溃（评测中
    任务中途工具崩溃→超时浪费）。两种编码都试，均失败则替换字符（不崩）。
    """
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    for enc in ("utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def _taskkill_cmd(pid: int, system_root: str = "") -> list:
    """taskkill 绝对路径（防 PATH 遮蔽——pi 同做法；纯函数便于测试）。"""
    root = system_root or os.environ.get("SystemRoot") or r"C:\Windows"
    return [os.path.join(root, "System32", "taskkill.exe"),
            "/F", "/T", "/PID", str(pid)]


def _kill_tree(proc) -> None:
    """超时终止：杀**进程树**（2026-09-27 审查实锤）。

    只杀 shell（cmd）会留下孤儿子进程继续改写工作区——原实现返回
    "command killed" 但子进程照常运行。Windows：taskkill /T（System32 绝对
    路径）；POSIX：killpg。
    """
    if os.name == "nt":
        try:
            subprocess.run(_taskkill_cmd(proc.pid),
                           capture_output=True, timeout=10, check=False)
            return
        except Exception as exc:  # taskkill 缺失等——回退直接杀
            logger.debug("taskkill 失败，回退直接杀进程：%s", exc)
    else:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            return
        except Exception as exc:
            logger.debug("killpg 失败，回退 proc.kill：%s", exc)
    try:
        proc.kill()
    except Exception as exc:
        logger.debug("进程回收失败（已退出/无权限）：%s", exc)


class BashTool(Tool):
    def __init__(self, ws, timeout: float = 120.0, sandbox_enabled: bool = True,
                 sandbox_mode: str = "native", container_template: str = "",
                 shell_path: str = ""):
        """sandbox_enabled：原生沙箱开关（默认开——工作区约束 + 敏感环境剥离）。

        BOX-2：sandbox_mode=container 时 bash 执行渲染 container_template，
        交给用户容器运行时（失败可见不回退）；模板须含 {workdir} 与
        {cmd}/{cmd_b64}（配置层已校验——此处纵深防御）。
        O1/O4：shell_path 为空时自动解析（Windows git-bash 默认主 terminal；
        WSL/PowerShell/cmd 可选档；macOS zsh 默认；Linux bash→sh）；关键字
        （git-bash/wsl/powershell/cmd/…）或绝对路径均可；解析失败 loud。
        """
        self._ws = ws
        self._timeout = float(timeout)
        self._sandbox_enabled = bool(sandbox_enabled)
        self._shell = shells.resolve_shell(shell_path)
        self._sandbox_mode = str(sandbox_mode or "native")
        if self._sandbox_mode not in MODES:
            raise ValueError(f"不支持的沙箱档位: {self._sandbox_mode}")
        self._container_template = str(container_template or "")
        if self._sandbox_mode == "container":
            validate_container_template(self._container_template)

    def name(self): return "bash"

    def description(self):
        if self._sandbox_mode == "container":
            return ("在用户外置容器内执行 shell 命令（沙箱: 外置容器档——命令经模板"
                    "路由到容器运行时；失败可见不回退；"
                    f"超时 {self._timeout:g}s 自动终止、输出超 {MAX_OUTPUT} 字符截断；"
                    "容器内环境由镜像/运行时决定）")
        label = _SHELL_LABEL.get(self._shell.kind, self._shell.kind)
        common = (f"命令面: {label}——{_SHELL_SEMANTICS.get(self._shell.kind, '自定义语义')}；"
                  "检索优先用 grep/glob 工具。")
        if self._sandbox_enabled:
            return ("在工作区内执行 shell 命令（沙箱: 开启——工作目录限定于工作区、"
                    "敏感环境变量剥离；网络允许；"
                    f"超时 {self._timeout:g}s 自动终止（可传 timeout 秒数覆盖，上限 600）、"
                    f"输出超 {MAX_OUTPUT} 字符保留末尾并全文落盘；{common}）")
        return ("在工作区内执行 shell 命令（沙箱: 关闭——继承本机环境；"
                f"超时 {self._timeout:g}s 自动终止（可传 timeout 参数覆盖，上限 600）、"
                f"输出超 {MAX_OUTPUT} 字符保留末尾并全文落盘；{common}）")

    def input_schema(self): return {"type": "object", "properties": {
        "command": {"type": "string"},
        "timeout": {"type": "number", "minimum": 1, "maximum": 600,
                    "description": "超时秒数（可选；默认 "
                    f"{self._timeout:g}s，上限 600）"}},
        "required": ["command"]}

    def _effective_timeout(self, timeout=None) -> float:
        """调用方 timeout（秒）覆盖默认值；clamp 1..600（坏值回退默认）。"""
        if timeout is None:
            return self._timeout
        try:
            t = float(timeout)
        except (TypeError, ValueError):
            return self._timeout
        return min(max(t, 1.0), 600.0)

    def _clean_env(self, environ=None) -> dict:
        """P3 T3：env 白名单（大小写不敏感——O1；key 原样保留）。

        缺失的系统关键变量注入保守默认（SystemRoot 等——Windows 子进程
        初始化需要；防裁剪环境/容器中 cmd/python 启动失败；判存同样不敏感）。
        Wave-1 Task B3：PATH 前置注入 git-bash 工具目录与 rg 目录——
        rg 保底与 cmd 回退档直接可用。
        """
        src = os.environ if environ is None else environ
        clean = {k: v for k, v in src.items() if _in_env_allow(k)}
        have = {k.lower() for k in clean}
        for k, v in {"SystemRoot": r"C:\Windows",
                     "WINDIR": r"C:\Windows"}.items():
            if k.lower() not in have:
                clean[k] = v
        inject = _unix_tool_dirs()
        try:
            from wuxing.tools.search_tools import find_ripgrep
            rg = find_ripgrep()
        except Exception as exc:  # 探测失败不阻断（搜索工具可选）
            logger.debug("ripgrep 探测失败（跳过注入）：%s", exc)
            rg = None
        if rg:
            rg_dir = str(pathlib.Path(rg).parent)
            if rg_dir not in inject:
                inject.append(rg_dir)
        if inject:
            path_key = next((k for k in clean if k.upper() == "PATH"),
                            "Path" if os.name == "nt" else "PATH")
            base = clean.get(path_key, os.environ.get(path_key, ""))
            clean[path_key] = os.pathsep.join(
                inject + ([base] if base else []))
        return clean

    def _truncate_with_spill(self, out: str, unit: str = "") -> tuple:
        """超限截断（保留末尾——构建/测试错误在尾部）+ 全文落盘（G6 复用）。

        落盘失败降级纯截断（note 不带路径）；不阻断命令结果返回。
        """
        if len(out) <= MAX_OUTPUT:
            return out, ""
        from wuxing.truncate_dump import dump_truncated
        path = dump_truncated(self._ws.root, out, unit=unit)
        where = (f"全文: {path}（用 read_file 读取）" if path
                 else "全文落盘失败")
        note = f"[输出超 {MAX_OUTPUT} 字符——已保留末尾；{where}]"
        return note + "\n" + out[-MAX_OUTPUT:], note

    def permission(self):
        # bash 能力面全开（execute/network/destructive）——由白名单+守卫+超时约束
        return {"read": True, "write": True, "execute": True,
                "network": True, "destructive": True}

    def route_info(self) -> dict:
        """执行路由元信息（trace/装配可见——BOX-2 M1；O1 增 shell 类型）。"""
        if self._sandbox_mode == "container":
            return {"sandbox_route": "container",
                    "sandbox_template_hash": template_hash(self._container_template)}
        return {"sandbox_route": "native", "shell": self._shell.kind}

    def execute(self, command="", timeout=None, **kw):
        if self._sandbox_mode == "container":
            try:
                cmd_line = render_container_command(
                    self._container_template, self._ws.root, command)
            except ValueError as e:
                from wuxing.protocols import ToolResult
                return ToolResult(status="error", tool_name=self.name(),
                                  error=f"container: 模板渲染失败: {e}")
            return self._run(cmd_line, container=True, timeout=timeout)
        res = self._run(command, container=False, timeout=timeout)
        self._attach_outside_write_note(command, res)
        return res

    def _attach_outside_write_note(self, command, res) -> None:
        """BOX-1：工作区外写入监控（审计可见——不硬阻断；危险类由守卫硬拦）。

        native 档专用——容器档（execute 分支）有意跳过：容器内写入不落宿主，
        审计面自然收窄（设计已披露；C4/E0-4 注释声明）。
        """
        from wuxing.outside_write import detect_outside_writes
        try:
            hits = detect_outside_writes(str(command or ""), self._ws.root)
        except Exception as exc:
            logger.debug("工作区外写入检测失败（不阻断）：%s", exc)
            return
        if not hits:
            return
        detail = "；".join(hits[:5])
        logger.warning("bash 工作区外写入疑似：%s", detail)
        note = f"[warn] 检测到工作区外写入目标（审计，不阻断）：{detail}"
        res.content = (note + "\n" + res.content) if res.content else note

    def _compose_command(self, cmd_line: str) -> str:
        """执行前命令整形：PowerShell 档前置 UTF-8 输出编码前导（pi/dsh 双源）。"""
        if self._shell is not None and self._shell.kind == "powershell":
            return _PS_UTF8_PREAMBLE + cmd_line
        return cmd_line

    def _run(self, cmd_line: str, *, container: bool, timeout=None):
        from wuxing.protocols import ToolResult
        prefix = "container: " if container else ""
        eff_timeout = self._effective_timeout(timeout)
        use_shell_cmd = container or not (self._shell and self._shell.path)
        if not container:
            cmd_line = self._compose_command(cmd_line)
        spawn_args = {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE,
                      "stdin": subprocess.DEVNULL,
                      "cwd": str(self._ws.root),
                      "env": self._clean_env() if self._sandbox_enabled else None,
                      "start_new_session": (os.name != "nt")}
        try:
            if use_shell_cmd:
                proc = subprocess.Popen(cmd_line, shell=True, **spawn_args)
            else:
                proc = subprocess.Popen(
                    self._shell.command_argv(cmd_line), shell=False, **spawn_args)
            try:
                raw_out, raw_err = proc.communicate(timeout=eff_timeout)
            except subprocess.TimeoutExpired:
                _kill_tree(proc)
                try:
                    proc.communicate(timeout=5)
                except Exception as exc:
                    logger.debug("超时回收输出失败（不掩超时事实）：%s", exc)
                return ToolResult(status="error", tool_name=self.name(),
                                  error=f"{prefix}timeout: command and descendants killed")
            rc = proc.returncode
            # 非零退出不 raise：结果（含 stderr）作为工具返回文本
            stdout = _decode_output(raw_out)
            stderr = _decode_output(raw_err)
            out = (stdout or "") + (("\n[stderr] " + stderr)
                                     if stderr and rc != 0 else "")
            if container and _runtime_failure(rc, stderr + "\n" + stdout):
                # 容器运行时级失败（启动/连接/命令缺失）——可见不回退 native
                detail = (stderr or stdout or "").strip()[:500] or "(no output)"
                return ToolResult(status="error", tool_name=self.name(),
                                  error=f"container: 容器运行时失败（exit {rc}）: {detail}")
            if out:
                content, _ = self._truncate_with_spill(out)
            else:
                content = f"(exit {rc})"
            return ToolResult(status="ok", content=content, tool_name=self.name())
        except Exception as e:
            return ToolResult(status="error", tool_name=self.name(),
                              error=f"{prefix}{e}")
