"""上下文压缩（2026-09-06：DSH 式——工具结果头尾保留+中间摘要）。

铁律（TokenPilot/知识库）：压缩点不破坏稳定前缀——压缩只作用于**尾部动态区**
（工具结果回填段），system 段逐字节不变（否则服务端缓存失效，省的钱还回去）。
"""
import re

HEAD_KEEP = 2000
TAIL_KEEP = 2000

# E3（企业级审查/DSH「超大结果分级处理」）：按规模分级——超大输出更激进裁剪
# （固定 2000 头尾对 1M 级输出仍占 4K——分级后 64K 以上逐级收紧）
_GRADED = [(64_000, 1500, 1500), (256_000, 800, 800)]


def _mid_note(size: int, head: int, tail: int, path: str | None) -> str:
    """中段注记（G6：落盘成功时携带全文路径）。"""
    suffix = f"（全文：{path}）" if path else ""
    return f"\n[中间 {size - head - tail} 字符已压缩{suffix}]\n"


def _compress_single(content: str, max_chars: int, head: int, tail: int,
                     path: str | None = None) -> str:
    """单条消息压缩：头部 head 字符 + 中间注记 + 尾部 tail 字符。

    E3：规模分级——超 64K 头尾收紧至 1500、超 256K 收紧至 800（不破坏
    头部/尾部关键信息（错误行/路径）前提下最大化中段裁剪——成本控制）。
    path（G6）：截断全文落盘相对路径——注记携带（None = 不带）。
    """
    if len(content) <= max_chars:
        return content
    size = len(content)
    for limit, h, t in _GRADED:
        if size > limit:
            head, tail = h, t  # 不 break——取最严格适用级（300K → 800 而非 1500）
    mid_note = _mid_note(size, head, tail, path)
    # C4（六轮审查）：头尾预算不得超出上限——极端小上限时按比例收缩，
    # 防「压缩」膨胀（原实现 head+tail+注记 > 原文：3500 @1000 → 4017）
    if head + tail + len(mid_note) > max_chars:
        avail = max(2, max_chars - len(mid_note) - 8)  # 8=缩放后注记字数波动的余量
        head = max(1, avail // 2)
        tail = max(0, avail - head)
        mid_note = _mid_note(size, head, tail, path)
    return content[:head] + mid_note + content[-tail:]


def project_task_context(task_text: str, max_chars: int = 400) -> str:
    """M1-2：任务上下文投影（CC「投影→决策」——确定性截断，无 LLM）。

    - 未超限：原样（零扰动）
    - 超限：保留开头（跨碎片/跨会话共享前缀）+ 尾注（超限说明）
    - 确定性：同输入同输出（同任务跨碎片一致——前缀共享与缓存键稳定保持）
    """
    t = str(task_text or "")
    if len(t) <= max_chars:
        return t
    return t[:max_chars] + f"\n…（任务背景过长已投影——原 {len(t)} 字符，完整背景见碎片目标语义）"


def _limit_for(content: str, default: int, tool_limits: dict | None) -> int:
    """工具来源 → 压缩上限（B，2026-09-11 报告 #6 数据裁决）。

    read_file 类数据保真（高上限）、bash 类日志受控——从包装标记/文本前缀
    解析 source；未列出工具用 default。
    """
    if not tool_limits:
        return default
    m = (re.match(r'<tool_result source="([^"]+)"', content)
         or re.match(r"\[tool(?::error)?\] (\w+):", content))
    if not m:
        return default
    try:
        return int(tool_limits.get(m.group(1), default) or default)
    except (TypeError, ValueError):
        return default


def compress_tool_results(messages: list, max_chars: int = 8192,
                          head: int = HEAD_KEEP, tail: int = TAIL_KEEP,
                          tool_limits: dict | None = None,
                          on_truncate=None) -> list:
    """压缩工具结果消息（user 角色且含工具结果标记——[tool] 前缀或 <tool_result> 边界）。

    L0-1（审查 A1）：runner 真实路径先 wrap 成 <tool_result> 再压缩——判定须同时
    兼容两种形态（旧 [tool] 行与新边界标记），否则压缩永不触发（回归）。
    仅处理动态回填段；system/其他消息原样返回（前缀零触碰）。
    tool_limits：按来源覆盖上限（B——read 64K/bash 16K/未列出用 max_chars）。
    on_truncate（G6）：实际截断时回调得到**压缩前全文**，返回值（相对路径或 None）
    拼入注记；回调异常吞掉（落盘失败不阻断压缩）。
    """
    out = []
    for m in messages:
        if m.get("role") == "system":
            out.append(m)  # 前缀不参与压缩（缓存红线）
            continue
        content = str(m.get("content", ""))
        if content.startswith(("[tool]", "[tool:error]", "[warn]", "[guard]",
                               "<tool_result")):
            limit = _limit_for(content, max_chars, tool_limits)
            path = None
            if on_truncate is not None and len(content) > limit:
                # G6：截断即落盘（压缩前全文；失败/None → 注记不带路径）
                try:
                    path = on_truncate(content)
                except Exception:  # 落盘失败不阻断压缩（观测不阻断）
                    path = None
            content = _compress_single(content, limit, head, tail,
                                       path=str(path) if path else None)
            out.append({"role": m.get("role", "user"), "content": content})
        else:
            out.append(m)
    return out
