"""A3（2026-09-22）：会话窗口预算与确定性优先级裁剪。

设计（`docs/WUXING_上下文窗口自选_A期设计_2026-09-22.md` §4）：预算 = 激进上界
估算 token（与 B 期投影同一估算器）；超预算时按固定优先级裁剪：

    system + 沙箱策略（机制必需，不裁）
    → skills / 共享经验（固定段，不裁）
    → FSC 回退摘要（最低：整段去）
    → 会话历史（保最近：从最旧收窄）
    → FSC 前缀（保最近：从最旧整条移除）

纪律：无预算（≤0）= 现状字节不变；所有裁剪仅投影层（池/存档零改写）；
trace `context_trimmed` 可回放。
"""
from __future__ import annotations

_DIGEST_PREFIX = "[上一轮碎片上下文]"
_HISTORY_PREFIX = "[会话历史]"
_SKILLS_PREFIX = "可用技能："
_SHARED_PREFIX = "[同任务已完成碎片的经验]"


def trim_text_tail(text: str, budget_tokens: int, estimator) -> tuple:
    """保留尾部、从最旧侧收窄；返回 (text, trimmed_chars)。单调估算下的二分。"""
    s = str(text or "")
    if s == "":
        return "", 0
    if budget_tokens <= 0:
        return "", len(s)
    if estimator(s) <= budget_tokens:
        return s, 0
    lo, hi = 0, len(s)
    while lo < hi:
        mid = (lo + hi) // 2
        if estimator(s[mid:]) <= budget_tokens:
            hi = mid
        else:
            lo = mid + 1
    return s[lo:], lo


def trim_text_tail_keep_header(text: str, budget_tokens: int, estimator) -> tuple:
    """保留首行头（如 `[会话历史]`）+ 尾部；返回 (text, trimmed_chars)。"""
    s = str(text or "")
    if "\n" not in s or budget_tokens <= 0:
        return trim_text_tail(s, budget_tokens, estimator)
    header, body = s.split("\n", 1)
    if estimator(header) >= budget_tokens:
        return "", len(s)
    body_trim, _cut = trim_text_tail(body, budget_tokens - estimator(header),
                                     estimator)
    result = header + (("\n" + body_trim) if body_trim else "")
    return result, len(s) - len(result)


def enforce_budget(messages: list, budget_tokens: int, estimator) -> tuple:
    """在装配后的消息列表上执行预算裁剪（通用；确定性）。

    返回 (messages, trimmed)：trimmed = [{"key": "digest|history|prefix", "chars": n}]。
    无预算（≤0）或已在预算内 → 原样返回（浅拷贝——外层不持有引用）。
    """
    msgs, trimmed, _kept = enforce_budget_indexed(
        messages, budget_tokens, estimator)
    return msgs, trimmed


def enforce_budget_indexed(messages: list, budget_tokens: int, estimator) -> tuple:
    """同 enforce_budget；额外返回保留消息的原始索引（升序）。

    预览侧按索引把裁剪结果精确映射回 FSC 前缀消息（同内容消息不串位）。
    """
    msgs = [dict(m) for m in (messages or [])]
    origin = {id(m): i for i, m in enumerate(msgs)}
    if budget_tokens <= 0 or not msgs:
        return msgs, [], [i for i in range(len(msgs))]

    def est(m: dict) -> int:
        return int(estimator(str(m.get("content", "")))) if m.get("content") else 0

    if sum(est(m) for m in msgs) <= budget_tokens:
        return msgs, [], [i for i in range(len(msgs))]
    trimmed: list = []
    start = 1 if (msgs and msgs[0].get("role") == "system") else 0

    # 1) FSC 回退摘要：最低优先级——整段去
    for i in range(start, len(msgs)):
        if str(msgs[i].get("content", "")).startswith(_DIGEST_PREFIX):
            trimmed.append({"key": "digest",
                            "chars": len(str(msgs[i].get("content", "")))})
            del msgs[i]
            break

    # 2) 会话历史：保最近——从最旧收窄（仅动历史段，其它固定）
    if sum(est(m) for m in msgs) > budget_tokens:
        for i in range(start, len(msgs)):
            content = str(msgs[i].get("content", ""))
            if not content.startswith(_HISTORY_PREFIX):
                continue
            others = sum(est(m) for m in msgs) - est(msgs[i])
            left = max(0, budget_tokens - others)
            shrunk, cut = trim_text_tail_keep_header(content, left, estimator)
            if cut:
                trimmed.append({"key": "history", "chars": cut})
            msgs[i]["content"] = shrunk
            break

    # 3) FSC 前缀：从最旧整条移除（保护 system/最后一条 user/技能/共享）
    #    回归修复（2026-10-03 真跑实证）：删除会使后续消息索引位移——keep
    #    必须按对象身份（id）判定，否则旧的索引会误删当前 prompt（input 清空
    #    → provider 400）；最后一条 user 无条件保护（不依赖 "[" 前缀判定）。
    keep = {0} if start == 1 else set()
    for i in range(len(msgs) - 1, -1, -1):
        if msgs[i].get("role") == "user":
            keep.add(i)
            break
    for i, m in enumerate(msgs):
        content = str(m.get("content", ""))
        if content.startswith((_SKILLS_PREFIX, _SHARED_PREFIX)):
            keep.add(i)
    keep_ids = {id(msgs[i]) for i in keep}
    i = start
    while sum(est(m) for m in msgs) > budget_tokens and i < len(msgs):
        if id(msgs[i]) in keep_ids:
            i += 1
            continue
        trimmed.append({"key": "prefix",
                        "chars": len(str(msgs[i].get("content", "")))})
        del msgs[i]
    return msgs, trimmed, [origin[id(m)] for m in msgs]


# ---- G7（2026-09-26）：自动压缩——窗口相对触发与滞回 ----
# E2-2（G7 v2 · 2026-10-03）：保留区比例封顶（DSH retainRatio 对齐）
KEEP_RATIO = 0.16


def auto_trigger_budget(cfg, window: int) -> int:
    """自动触发线（token）：min(window×ratio, window − reserve − output_reserve)。

    E2-2（DSH §2.3 对齐）：比例上限 + 输出/余量头寸。
    REAL-18（延续）：窗口过小/配置不当使任一头寸 ≤ 0 → **禁用自动链**（0），
    不得把触发线退化为极端裁剪；非法 ratio（不在 (0,1]）→ 禁用（fail-closed）。
    """
    if not bool(getattr(cfg, "auto_trim_enabled", True)):
        return 0
    try:
        w = int(window or 0)
        r = int(getattr(cfg, "auto_trim_reserve_tokens", 16384) or 0)
        o = int(getattr(cfg, "auto_trim_output_reserve_tokens", 8192) or 0)
        ratio = float(getattr(cfg, "auto_trim_trigger_ratio", 0.8) or 0.0)
    except (TypeError, ValueError):
        # 非法预算输入（None/非数）→ 0：调用方禁用自动裁剪
        return 0
    if w <= 0 or r < 0 or o < 0 or not (0 < ratio <= 1):
        return 0
    headroom = w - r - o
    trigger = min(int(w * ratio), headroom)
    if headroom <= 0 or trigger <= 0:
        return 0
    return trigger


def effective_keep_recent(cfg, window: int) -> int:
    """LLM 链保留区（token）：绝对保留值，以 (W−O)×16% 封顶（E2-2 · K2）。

    小窗口下保护输出头寸并逼近比例模型；窗口未知 → 用绝对值（不臆断）。
    """
    try:
        keep = max(0, int(getattr(cfg, "auto_compact_keep_recent_tokens",
                                   20000) or 0))
        w = int(window or 0)
        o = max(0, int(getattr(cfg, "auto_trim_output_reserve_tokens",
                               8192) or 0))
    except (TypeError, ValueError):
        # 非法输入（None/非数）→ 0：无保留区（该链不可用，调用方自会判断跨度）
        return 0
    if w <= 0:
        return keep
    cap = int(max(0, w - o) * KEEP_RATIO)
    return min(keep, cap) if cap > 0 else keep


def trim_target(cfg, window: int, trigger: int) -> int:
    """滞回目标线：max(window−2×reserve, window/2)，以触发线为上限（防小窗口倒挂）。"""
    try:
        w = int(window or 0)
        r = int(getattr(cfg, "auto_trim_reserve_tokens", 16384) or 0)
    except (TypeError, ValueError):
        return max(1, int(trigger or 1))
    if w <= 0:  # 窗口非法：无滞回可算——目标=触发线
        return max(1, int(trigger or 1))
    target = max(w // 2, w - 2 * r)
    return max(1, min(int(trigger or 1), target))


def effective_budget(cfg, window: int, session_budget: int = 0) -> int:
    """有效触发预算：会话预算优先（>0）；否则自动触发线；0 = 不裁剪（现状）。"""
    try:
        sb = int(session_budget or 0)
    except (TypeError, ValueError):
        sb = 0
    if sb > 0:
        return sb
    return auto_trigger_budget(cfg, window)


def apply_auto_trim(messages: list, cfg, window: int, estimator,
                    session_budget: int = 0) -> tuple:
    """A3 预算执行（G7 扩展）：会话预算优先；否则自动链（超触发线 → 裁至滞回目标线）。

    返回 (messages, trimmed, budget_used, auto)：
      - 会话预算 > 0：既有 enforce_budget（逐字节不变语义）；auto=False
      - 自动链未触发/未启用：原样返回、budget_used=0、auto=False（零行为）
    """
    try:
        sb = int(session_budget or 0)
    except (TypeError, ValueError):
        sb = 0
    if sb > 0:
        out, trimmed = enforce_budget(messages, sb, estimator)
        return out, trimmed, sb, False
    trigger = auto_trigger_budget(cfg, window)
    if trigger <= 0:
        return messages, [], 0, False
    est_total = 0
    for m in messages or []:
        est_total += estimator(str(m.get("content", "")))
    if est_total <= trigger:
        return messages, [], 0, False
    target = trim_target(cfg, window, trigger)
    out, trimmed = enforce_budget(messages, target, estimator)
    return out, trimmed, target, True


def trim_oldest_chunks(messages: list, budget_tokens: int, estimator) -> tuple:
    """溢出恢复：配对安全裁剪（G7 v2 · PP5）——按 user 消息切块，从最旧整块移除。

    块边界 = user 消息起点 → assistant tool_calls 与其 tool 结果同块，不拆散。
    保护：system 前言块；最后一块（当前轮）；`[技能`/`[共享` 前缀块。
    返回 (messages, removed_chunks, removed_chars)；无可移除 → (原消息, 0, 0)。
    """
    msgs = [dict(m) for m in (messages or [])]
    if not msgs:
        return msgs, 0, 0

    def est(m):
        return int(estimator(str(m.get("content", "")))) \
            if m.get("content") else 0

    total = sum(est(m) for m in msgs)
    if total <= budget_tokens:
        return msgs, 0, 0
    starts = [i for i, m in enumerate(msgs) if m.get("role") == "user"]
    if not starts:
        return msgs, 0, 0
    chunks = []
    if starts[0] > 0:
        chunks.append((0, starts[0]))          # system 前言（保护）
    for j, s in enumerate(starts):
        e = starts[j + 1] if j + 1 < len(starts) else len(msgs)
        chunks.append((s, e))
    protected = {len(chunks) - 1}              # 最后一块 = 当前轮
    if starts[0] > 0:
        protected.add(0)
    for idx, (b, _e) in enumerate(chunks):
        if str(msgs[b].get("content", "")).startswith(("[技能", "[共享")):
            protected.add(idx)
    drop, removed, removed_chars = set(), 0, 0
    for idx, (b, e) in enumerate(chunks):
        if total <= budget_tokens:
            break
        if idx in protected:
            continue
        chars = sum(est(msgs[i]) for i in range(b, e))
        drop.update(range(b, e))
        removed += 1
        removed_chars += chars
        total -= chars
    if not removed:
        return msgs, 0, 0
    out = [m for i, m in enumerate(msgs) if i not in drop]
    return out, removed, removed_chars
