"""SEC1 内容信任层：信封不可伪造 + 隐形字符清除 + 高置信注入模式中和。

设计：docs/WUXING_安全三件套_设计_2026-09-30.md §2（裁决 B——实验接入）。
纪律：模式清单保持「窄而高置信」；替换为可见标记（不静默删除）；
findings 供 trace 审计；工作区源文件不被修改（只作用于消息装配）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

REDACTED = "【已中和-疑似注入】"

# 信封标签（大小写不敏感；属性值也需中和——source/status 可控）
_BOUNDARY_RES = (
    (re.compile(r"</tool_result", re.IGNORECASE), "&lt;/tool_result"),
    (re.compile(r"<tool_result", re.IGNORECASE), "&lt;tool_result"),
)

# 隐形/双向控制字符（客观安全，几乎无误伤）
_INVISIBLE_RE = re.compile(
    "[\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff\u00ad]")

# 高置信注入短语（窄清单——设计 §2.5；新增需附测试与理由）
_PATTERN_RES = (
    ("instructions-override", re.compile(
        r"ignore\s+(the\s+)?(all\s+)?(previous|prior|above)\s+instructions?",
        re.IGNORECASE)),
    ("disregard", re.compile(
        r"disregard\s+(the\s+)?(previous|prior|above)", re.IGNORECASE)),
    ("forget", re.compile(
        r"forget\s+(all\s+)?(previous|prior|everything)", re.IGNORECASE)),
    ("new-instructions", re.compile(r"new\s+instructions?[:\s]", re.IGNORECASE)),
    ("you-are-now", re.compile(r"you\s+are\s+now\b", re.IGNORECASE)),
    ("system-tag", re.compile(r"</?\s*system\s*>", re.IGNORECASE)),
    # C1（E0-4 模式演进 2026-10-03）：宾语窄化——仅在接「指令/规则类」宾语时命中；
    # 日常用语「忽略之前的错误」不再标记（P2-1 实锤；设计 §2.7 已披露误报↔漏报权衡）
    ("zh-忽略", re.compile(
        r"忽略(以上|之前|前面|上述)(的)?(所有|全部)?"
        r"(指令|指示|提示|提示词|命令|规则|要求|设定|说明)")),
    ("zh-无视", re.compile(
        r"无视(以上|之前|上述)(的)?(所有|全部)?"
        r"(指令|指示|提示|提示词|命令|规则|要求|设定|说明)")),
    ("zh-你现在是", re.compile(r"你现在是")),
    ("zh-新的指令", re.compile(r"新的指令[：:]")),
    ("zh-系统提示词", re.compile(r"系统提示词[：:]")),
    # E2-4（H3 补扫）：外泄意图词（窄——仅不可信内容面；工作区合法任务文本不经此净化）
    ("exfiltration", re.compile(r"\bexfiltrat\w*", re.IGNORECASE)),
)


@dataclass
class SanitizeResult:
    clean: str
    findings: list = field(default_factory=list)  # {kind, count|name, sample?}


def _escape_boundaries_counted(text: str) -> tuple:
    """中和信封标签并返回真实替换数（C2：审计精度——非恒 1）。"""
    out = str(text or "")
    n = 0
    for rx, repl in _BOUNDARY_RES:
        out, k = rx.subn(repl, out)
        n += k
    return out, n


def escape_boundaries(text: str) -> str:
    """中和内容中的信封标签序列（防伪边界逃逸）。"""
    return _escape_boundaries_counted(text)[0]


def strip_invisibles(text: str) -> str:
    """剥离零宽/双向控制字符（保留其余内容原样）。"""
    return _INVISIBLE_RE.sub("", str(text or ""))


def redact_injection_patterns(text: str) -> tuple:
    """高置信注入短语 → 可见标记；返回 (文本, 命中模式名列表)。"""
    out = str(text or "")
    hits = []
    for name, rx in _PATTERN_RES:
        out, n = rx.subn(REDACTED, out)
        if n:
            hits.append(name)
    return out, hits


def sanitize_untrusted(text: str) -> SanitizeResult:
    """三步串联：隐形剥离 → 模式中和 → 边界中和。

    顺序纪律（审查修复 2026-09-30）：剥离必须先于模式中和——否则
    隐形字符可拆散触发短语绕过检测，且剥离后留下未标记短语（洗白）；
    边界中和最后执行（剥离已使隐形字符无法拆散信封标签）。
    """
    raw = str(text or "")
    stripped = strip_invisibles(raw)
    after_redact, hits = redact_injection_patterns(stripped)
    escaped, boundary_n = _escape_boundaries_counted(after_redact)
    findings = []
    for name in hits:
        findings.append({"kind": "pattern", "name": name, "sample": raw[:40]})
    removed = len(raw) - len(stripped)
    if removed:
        findings.append({"kind": "invisible", "count": removed})
    if boundary_n:
        findings.append({"kind": "boundary", "count": boundary_n})
    return SanitizeResult(clean=escaped, findings=findings)
