"""系统原生对话框桥（R1-1/R2-1 · 用户裁决 2026-09-15）。

单机单用户前提：壳服务与用户在同一个桌面会话，对话框在用户屏幕弹出。
实现 = 子进程 tkinter（新进程自带主线程与事件循环——不污染服务线程）。
失败（tkinter 缺失/无桌面会话）→ RuntimeError（端点转 503 返回——失败可见）。
"""
import os
import pathlib
import subprocess
import sys

_PICK_FN = {
    "file": "askopenfilename",
    "files": "askopenfilenames",
    "directory": "askdirectory",
}


def _interpreter() -> str:
    """Windows 优先同目录 pythonw.exe（无控制台子系统——不闪命令行窗口）。"""
    exe = pathlib.Path(sys.executable)
    if os.name == "nt":
        candidate = exe.with_name("pythonw.exe")
        if candidate.is_file():
            return str(candidate)
    return sys.executable


def _no_window_flags() -> int:
    """CREATE_NO_WINDOW（0x08000000）双保险：即使走 python.exe 也不弹控制台。"""
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _dialog_code(kind: str, title: str) -> str:
    fn = _PICK_FN[kind]
    if kind == "files":
        collect = "print('\\n'.join(str(p) for p in (res or ())))"
    else:
        collect = "print(res or '')"
    return (
        "import tkinter as tk\n"
        "from tkinter import filedialog\n"
        "root = tk.Tk()\n"
        "root.withdraw()\n"
        "root.attributes('-topmost', True)\n"
        f"res = filedialog.{fn}(title={title!r})\n"
        f"{collect}\n"
        "root.destroy()\n"
    )


def pick(kind: str = "file", title: str = "WUXING",
         timeout: float = 600.0) -> list[str]:
    """弹系统对话框 → 路径列表（取消/无选择 → []）。"""
    if kind not in _PICK_FN:
        raise ValueError(f"未知对话框类型：{kind}")
    code = _dialog_code(kind, title)
    try:
        out = subprocess.run([_interpreter(), "-c", code],
                             capture_output=True, text=True, timeout=timeout,
                             check=False, creationflags=_no_window_flags())
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"系统对话框不可用：{exc}") from exc
    # 黄金测试修复（2026-09-30）：子进程失败不得静默返回 []——
    # 旧实现丢弃 returncode/stderr →「选中后无路径→回退弹窗」不可诊断。
    if int(getattr(out, "returncode", 0) or 0) != 0:
        detail = " ".join(str(getattr(out, "stderr", "") or "").strip().split())
        raise RuntimeError(
            f"系统对话框失败（exit {out.returncode}）：{detail[:300] or '无错误输出'}")
    return [ln.strip() for ln in (out.stdout or "").splitlines() if ln.strip()]
