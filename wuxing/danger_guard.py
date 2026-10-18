"""危险命令拦截（P5：工具执行前守卫——Pi tool_call 拦截思想落地）。

保守策略（默认）：危险即拦截（sudo 一律拦、根级/盘符/家目录级删除一律拦、
**相对路径逃逸（.. 段）删除一律拦**）。
工作区相对路径（rm build/、rm src/old.py）放行——bash cwd 已限定工作区（P2），
普通相对删除无逃逸风险；`..` 逃逸、绝对路径（C:/、/、~）拦截。

2026-09-27 四因素审查补齐（实弹验证的覆盖缺口）：
- `rm -rf ../..` 等相对逃逸（旧注释「相对删除无逃逸风险」不成立——`..` 段可跳出 cwd）；
  连通捕 `cd .. && rm x` 组合（删除命令 + 任一段 `..` → 拦）。
- `del` 递归/静默标志**任意顺序**（旧模式仅匹配 `/q` 紧跟 del——`del /s /q` 被放行）。
- `rd`（rmdir 别名）递归删除。
- PowerShell `Remove-Item -Recurse/-Force`。

BOX-M3 持续沉淀（2026-09-28，非删除类破坏命令——外溢后果不可逆）：
- `format X:` 磁盘格式化 / `shutdown /x|-x` 关机重启（带参数才拦——防误伤文案）/
  `reg delete` 注册表删除 / `mkfs` 文件系统格式化 / `dd of=/dev/` 设备覆写。
"""
import re

DANGER_PATTERNS = [
    # 删除目标为绝对路径（/ 开头、盘符 X:、家目录 ~）——cwd 已限工作区（P2），
    # 相对路径（含跨目录 rm src/old.py）放行；审查修正：旧正则把任意含斜杠的相对路径误拦
    (r"\brm\b[^\n]*?\s(?:/(?:[^\s]*)|[A-Za-z]:(?:[\\/][^\s]*)?|~(?:[\\/]?[^\s]*))",
     "根/盘符/家目录删除"),
    (r"\bsudo\b", "提权命令"),
    # del/erase 递归（/s）或静默（/q）——标志与命令的先后、多个标志的组合无关
    (r"\b(?:del|erase)\b[^\n]*(?:/[sq]\b)", "Windows 静默/递归删除"),
    # rmdir 及其别名 rd 的递归删除
    (r"\b(?:rmdir|rd)\b[^\n]*(?:/s\b)", "Windows 递归目录删除"),
    # PowerShell 删除小径：-Recurse/-Force（含 -r/-f 简写）
    (r"\bRemove-Item\b[^\n]*-(?:recurse|force|r|f)\b", "PowerShell 递归/强制删除"),
    # BOX-M3（2026-09-28）持续沉淀：非删除类破坏命令（外溢后果不可逆）
    (r"\bformat\b\s+[A-Za-z]:", "磁盘格式化"),
    (r"\bshutdown\b\s+(?:/[a-z]\b|-\w)", "关机/重启（带参数）"),
    (r"\breg\s+delete\b", "注册表删除"),
    (r"\bmkfs\b", "格式化文件系统"),
    (r"\bdd\b[^\n]*\bof=/dev/", "dd 覆写设备"),
]

# 删除类命令 + 路径 `..` 段 → 逃逸删除（cwd 沙箱兜不住；
# 连同「cd .. && rm x」组合一并拦——保守口径：同行出现两者即拦）
_DELETE_CMD_RE = re.compile(r"\b(?:rm|del|erase|rd|rmdir|Remove-Item)\b",
                            re.IGNORECASE)
# `..` 作为路径段：前界为行首/空白/引号/等号/冒号/斜杠，后界为斜杠/空白/引号/行尾
_TRAVERSAL_SEG_RE = re.compile(r"(?:^|[\s\"'=:\\/])\.\.(?:[\\/]|[\s\"']|$)")


def check_command(command: str,
                  profile: str = "workspace-write") -> str | None:
    """返回拦截原因（None=放行）——供事件/界面透出。

    SEC3：full-access 放宽**路径类**约束（相对逃逸删除）；
    危险命令黑名单（根/盘符/家目录删除、format、shutdown、reg delete、
    mkfs、dd）恒定拦截。
    """
    cmd = str(command or "")
    for pattern, reason in DANGER_PATTERNS:
        if re.search(pattern, cmd, re.IGNORECASE):
            return reason
    if (profile != "full-access" and _DELETE_CMD_RE.search(cmd)
            and _TRAVERSAL_SEG_RE.search(cmd)):
        return "相对路径逃逸删除"
    return None


def guard_command(command: str, profile: str = "workspace-write") -> bool:
    """返回 True=允许，False=拦截。"""
    return check_command(command, profile=profile) is None
