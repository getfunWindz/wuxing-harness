"""BOX-1：bash 面工作区外写入监控——静态检测（保守；审计可见，不硬阻断）。

口径（用户裁决 2026-09-30）：检测 + 可见提示；危险类命令仍由 danger_guard
硬拦截。硬阻断全部外部写入会误伤合法用法（缓存/临时目录/工具链），
故本条以「可审计、可归因」为目标。

检测面（静态、保守）：
- 重定向目标（> / >>）解析后落在工作区外 → 命中（排除 /dev/null、NUL）；
- 写入类命令（cp/mv/mkdir/touch/tee/Set-Content…）的路径参数越界 → 命中。

盲区（如实声明）：变量展开（$TMP/%TEMP%）、脚本内动态写入、管道下游间接写入。
边界（C4/E0-4）：引号内字面 `>` 不误报（引号感知扫描）；`2>&1` 类 fd 复制不计；
容器档（sandbox_mode=container）不适用——写入不落宿主，bash_tool 有意跳过（注释声明）。
"""
from __future__ import annotations

import os
import pathlib
import re

_EXCLUDE = {"nul", "nul:", "/dev/null", "$null"}
_WRITE_CMDS = {"cp", "mv", "move", "copy", "xcopy", "robocopy", "mkdir", "md",
               "touch", "tee", "new-item", "set-content", "out-file",
               "add-content", "ni", "sc"}
_TOKEN_RE = re.compile(r"\"[^\"]+\"|'[^']+'|\S+")
_ABS_RE = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\|/)")


def _strip_q(token: str) -> str:
    t = str(token).strip()
    if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'":
        return t[1:-1]
    return t


def _resolve(token: str, root: pathlib.Path) -> pathlib.Path:
    p = pathlib.Path(token)
    if not p.is_absolute():
        p = root / p
    s = os.path.realpath(str(p))
    return pathlib.Path(s.removeprefix("\\\\?\\"))


def _outside(token: str, root: pathlib.Path) -> bool:
    t = _strip_q(token)
    if not t or t.lower() in _EXCLUDE:
        return False
    try:
        target = _resolve(t, root)
        return not target.is_relative_to(root)
    except (OSError, ValueError):
        # 解析失败 → 不判界外（保守检测：宁漏不误伤；危险命令由 danger_guard 兜底）
        return False


def _pathish(token: str) -> bool:
    t = _strip_q(token)
    return bool(t) and ("/" in t or "\\" in t or ".." in t
                        or bool(_ABS_RE.match(t)))


def _iter_redirect_targets(cmd: str):
    """引号感知的重定向目标扫描（C4）：字面 `>` 不误报；无空格重定向可见。

    规则：引号内字符不参与扫描；`>`/`>>` 后取一个目标 token（引号目标取至
    配对引号；裸目标止于空白/控制符）；`>&`（fd 复制）无路径 → 不计。
    """
    i, n = 0, len(cmd)
    quote = ""
    while i < n:
        ch = cmd[i]
        if quote:
            if ch == quote:
                quote = ""
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            i += 1
            continue
        if ch != ">":
            i += 1
            continue
        j = i + 1
        if j < n and cmd[j] == ">":  # append `>>`
            j += 1
        while j < n and cmd[j] in " \t":
            j += 1
        if j >= n:
            break
        if cmd[j] in ("'", '"'):
            q = cmd[j]
            k = j + 1
            while k < n and cmd[k] != q:
                k += 1
            yield cmd[j:k + 1]
            i = (k + 1) if k < n else n
            continue
        k = j
        while k < n and cmd[k] not in " \t;&|<>":
            k += 1
        if k > j:
            yield cmd[j:k]
            i = k
            continue
        i = j  # `>&1` 等无路径目标——跳过


def detect_outside_writes(command: str, root: pathlib.Path) -> list[str]:
    """返回疑似工作区外写入描述列表（空=未发现；审计用途，不阻断）。"""
    cmd = str(command or "")
    root = pathlib.Path(os.path.realpath(str(root)))
    hits: list[str] = []
    for target in _iter_redirect_targets(cmd):
        if _outside(target, root):
            hits.append(f"重定向 → {_strip_q(target)}")
    for seg in re.split(r"&&|\|\||[;\n|]", cmd):
        tokens = _TOKEN_RE.findall(seg.strip())
        if not tokens:
            continue
        name = pathlib.PurePath(_strip_q(tokens[0]).lower()).name
        name = name.removesuffix(".exe")
        if name not in _WRITE_CMDS:
            continue
        for tok in tokens[1:]:
            if tok.startswith("-"):
                continue
            if _pathish(tok) and _outside(tok, root):
                hits.append(f"{name} → {_strip_q(tok)}")
    return hits
