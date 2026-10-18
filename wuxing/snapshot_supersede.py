"""O2-2 P2：旧快照替换（投影层 keep-latest）——防上下文膨胀。

设计：`docs/WUXING_内置浏览器体验断言_设计_2026-10-07.md` §4.2（Gemini
`snapshotSuperseder` 先例）——新快照生成后，历史中的旧快照块替换为占位。
纪律：仅作用于注入投影（存档零改写——G3）；确定性、幂等。

匹配两种形态：
  1. PE-1 信封（现役）：`<tool_result source="browser_snapshot">…</tool_result>`
  2. 旧行式（历史会话）：`[tool] browser_snapshot: …`（至下一 `\\n[` 标记或末尾）
"""
import re

PLACEHOLDER = "[旧快照已被替换]"

_ENVELOPE_RE = re.compile(
    r'<tool_result source="browser_snapshot">\n.*?\n</tool_result>',
    re.DOTALL,
)
_LEGACY_RE = re.compile(r"\[tool\] browser_snapshot:[^\n]*(?:\n(?!\[)[^\n]*)*")

_ENVELOPE_PLACEHOLDER = (
    f'<tool_result source="browser_snapshot">\n{PLACEHOLDER}\n</tool_result>'
)
_LEGACY_PLACEHOLDER = f"[tool] browser_snapshot: {PLACEHOLDER}"


def supersede_old_snapshots(messages: list) -> int:
    """就地替换旧快照块（保留最后一块）；返回替换数（0=无操作）。

    - system 消息不处理；无快照 → 0；
    - 已经是占位的块不再计入（幂等）；信封内伪 legacy 标记不二次处理（重叠保护）。
    """
    matches: list = []  # (msg_index, start, end, kind)
    for i, m in enumerate(messages):
        if str(m.get("role", "")) == "system":
            continue
        content = str(m.get("content", ""))
        if "browser_snapshot" not in content:
            continue
        env_spans: list = []
        for mr in _ENVELOPE_RE.finditer(content):
            env_spans.append((mr.start(), mr.end()))
            if PLACEHOLDER in mr.group(0):
                continue  # 已是占位（幂等）
            matches.append((i, mr.start(), mr.end(), "envelope"))
        for mr in _LEGACY_RE.finditer(content):
            if PLACEHOLDER in mr.group(0):
                continue
            if any(s <= mr.start() < e for s, e in env_spans):
                continue  # 信封内伪标记（重叠保护）
            matches.append((i, mr.start(), mr.end(), "legacy"))
    if len(matches) <= 1:
        return 0
    keep = max(matches, key=lambda x: (x[0], x[1]))
    by_msg: dict = {}
    for (i, start, end, kind) in matches:
        if (i, start, end, kind) == keep:
            continue
        by_msg.setdefault(i, []).append((start, end, kind))
    replaced = 0
    for i, spans in by_msg.items():
        content = str(messages[i].get("content", ""))
        for (start, end, kind) in sorted(spans, reverse=True):
            placeholder = (_ENVELOPE_PLACEHOLDER if kind == "envelope"
                           else _LEGACY_PLACEHOLDER)
            content = content[:start] + placeholder + content[end:]
            replaced += 1
        messages[i] = {**messages[i], "content": content}
    return replaced
