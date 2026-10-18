"""跨平台 shell 解析（O1/O4 · 2026-10-07 用户声明 + 评审修订）。

Windows：**git-bash 默认主 terminal**；WSL / PowerShell / cmd 为**可选档**
（关键字或绝对路径；调用参数按 kind 适配）。macOS：**zsh 默认**（用户可
配置其他）；Linux：bash→sh。config `bash_shell_path` 三种形态：空=自动 /
关键字（git-bash·wsl·powershell·pwsh·cmd·zsh·bash·sh）/ 绝对路径（kind 按
文件名推断）；解析失败 loud（不静默回退）。
代码构写参考（调研 §2.3）：pi `getShellConfig`/`getPowerShellConfig`、
opencode `Shell`（META/args/fallback=darwin zsh/git 反推）、DSH shellDialect。
调研：docs/WUXING_bash工具调研_2026-10-07.md。
"""
from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass


def _args_for(kind: str) -> tuple:
    """kind → 调用参数（pi PowerShell flags / opencode args() / cmd·wsl 实测）。"""
    if kind == "powershell":
        return ("-NoProfile", "-NonInteractive",
                "-ExecutionPolicy", "Bypass", "-Command")
    if kind == "cmd":
        return ("/d", "/s", "/c")
    if kind == "wsl":
        return ("-e", "bash", "-c")
    return ("-c",)


@dataclass(frozen=True)
class ShellSpec:
    """path 为空 = 平台默认回退（Windows 无 bash 时 cmd 语义）。"""

    path: str
    args: tuple = ("-c",)
    kind: str = "bash"  # bash|zsh|posix|powershell|cmd|wsl|custom

    def command_argv(self, command: str) -> list:
        return [self.path, *self.args, str(command)]


_WSL_SUFFIXES = ("\\system32\\bash.exe", "\\sysnative\\bash.exe",
                 "\\windowsapps\\bash.exe")
_KEYWORDS = ("git-bash", "wsl", "powershell", "pwsh", "cmd",
             "zsh", "bash", "sh")


def is_wsl_bash(path: str) -> bool:
    """WSL 型 bash 判定（System32/Sysnative/WindowsApps 启动器——语义在 Linux VM）。"""
    norm = str(path or "").replace("/", "\\").lower()
    return any(norm.endswith(s) for s in _WSL_SUFFIXES)


def git_bash_candidates(env=None, which=None) -> list:
    """Git for Windows 已知安装位置（bin/usr-bin；ProgramFiles 与 x86；
    git.exe 反推安装根——opencode `gitbash()` 同思路）。"""
    env = os.environ if env is None else env
    out = []
    for key in ("ProgramFiles", "ProgramFiles(x86)"):
        base = str(env.get(key) or "").rstrip("\\/")
        if base:
            out.append(base + "\\Git\\bin\\bash.exe")
            out.append(base + "\\Git\\usr\\bin\\bash.exe")
    if which is not None:
        git = which("git")
        if git:
            root = str(git).replace("/", "\\").rsplit("\\", 2)[0]
            out.append(root + "\\bin\\bash.exe")
            out.append(root + "\\usr\\bin\\bash.exe")
    return out


def _env_get_ci(env, key: str):
    src = os.environ if env is None else env
    for k, v in src.items():
        if str(k).lower() == key.lower() and v:
            return str(v)
    return None


def _system_root(env) -> str:
    return _env_get_ci(env, "SystemRoot") or r"C:\Windows"


def _spec(path: str, kind: str = "") -> ShellSpec:
    k = kind or _kind_for(path)
    return ShellSpec(path=str(path), args=_args_for(k), kind=k)


def _kind_for(path: str) -> str:
    name = str(path).replace("\\", "/").rsplit("/", 1)[-1].lower()
    if name in ("powershell", "powershell.exe", "pwsh", "pwsh.exe"):
        return "powershell"
    if name in ("wsl", "wsl.exe"):
        return "wsl"
    if name.startswith("cmd"):
        return "cmd"
    if "bash" in name:
        return "bash"
    if name in ("zsh", "zsh.exe"):
        return "zsh"
    if name in ("sh", "sh.exe", "dash", "dash.exe"):
        return "posix"
    return "custom"


def _auto_windows(which, exists, env) -> ShellSpec:
    for cand in git_bash_candidates(env, which):
        if exists(cand):
            return _spec(cand, "bash")
    found = which("bash")
    if found and not is_wsl_bash(found):
        return _spec(found, "bash")
    return ShellSpec(path="", kind="cmd")  # 回退档（描述/trace 可见上报）


def _auto_darwin(which, exists) -> ShellSpec:
    """macOS：zsh 默认（用户声明）；缺失回退 bash→sh。"""
    if exists("/bin/zsh"):
        return _spec("/bin/zsh", "zsh")
    found = which("zsh")
    if found:
        return _spec(str(found), "zsh")
    if exists("/bin/bash"):
        return _spec("/bin/bash", "bash")
    found = which("bash")
    if found:
        return _spec(str(found), "bash")
    return _spec("/bin/sh", "posix")


def _auto_posix(which, exists) -> ShellSpec:
    if exists("/bin/bash"):
        return _spec("/bin/bash", "bash")
    found = which("bash")
    if found:
        return _spec(str(found), "bash")
    return _spec("/bin/sh", "posix")


def _resolve_keyword(key: str, which, exists, env) -> ShellSpec:
    """可选档关键字：git-bash / wsl / powershell / pwsh / cmd / zsh / bash / sh。"""
    if key == "git-bash":
        for cand in git_bash_candidates(env, which):
            if exists(cand):
                return _spec(cand, "bash")
        found = which("bash")
        if found and not is_wsl_bash(found):
            return _spec(str(found), "bash")
        raise ValueError("git-bash 未找到（ProgramFiles/PATH 均无 bash）")
    if key == "wsl":
        cands = [os.path.join(_system_root(env), "System32", "wsl.exe")]
        for name in ("wsl", "wsl.exe"):
            c = which(name)
            if c:
                cands.append(str(c))
        for c in cands:
            if exists(c):
                return _spec(c, "wsl")
        raise ValueError("wsl 未找到（wsl.exe 不存在）")
    if key in ("powershell", "pwsh"):
        for name in ("pwsh", "pwsh.exe", "powershell", "powershell.exe"):
            c = which(name)
            if c:
                return _spec(str(c), "powershell")
        ps51 = os.path.join(_system_root(env), "System32",
                            "WindowsPowerShell", "v1.0", "powershell.exe")
        if exists(ps51):
            return _spec(ps51, "powershell")
        raise ValueError("powershell 未找到（pwsh/powershell 均无）")
    if key == "cmd":
        cands = []
        comspec = _env_get_ci(env, "COMSPEC")
        if comspec:
            cands.append(comspec)
        cands.append(os.path.join(_system_root(env), "System32", "cmd.exe"))
        for name in ("cmd", "cmd.exe"):
            c = which(name)
            if c:
                cands.append(str(c))
        for c in cands:
            if exists(c):
                return _spec(c, "cmd")
        raise ValueError("cmd 未找到")
    # zsh / bash / sh：POSIX 关键字精确解析
    kind = {"zsh": "zsh", "bash": "bash", "sh": "posix"}[key]
    posix_path = f"/bin/{key}"
    if exists(posix_path):
        return _spec(posix_path, kind)
    found = which(key)
    if found:
        return _spec(str(found), kind)
    raise ValueError(f"{key} 未找到")


def resolve_shell(choice: str = "", *, platform: str = "", which=None,
                  exists=None, env=None) -> ShellSpec:
    """解析 shell。choice：空=自动 / 关键字 / 绝对路径。

    探测函数可注入（测试）；路径缺失或关键字解析失败 → ValueError（loud）。
    """
    which = shutil.which if which is None else which
    exists = os.path.isfile if exists is None else exists
    if choice:
        key = str(choice).strip().lower()
        if key in _KEYWORDS:
            return _resolve_keyword(key, which, exists, env)
        if not exists(choice):
            raise ValueError(f"bash_shell_path 不存在: {choice}")
        return _spec(choice)
    plat = platform or sys.platform
    if plat in ("nt", "win32"):
        return _auto_windows(which, exists, env)
    if plat == "darwin":
        return _auto_darwin(which, exists)
    return _auto_posix(which, exists)
