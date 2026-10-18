"""新会话承接简报（双模式批 4 · 设计 §6）：确定性拼装（无 LLM）。

用途：黄金期严管档「一键新会话承接」——把要点（最近轮次/产物/地图摘要）带入
新会话输入区，用户确认/编辑后发送（调用方不自动提交）。
"""
from __future__ import annotations

import pathlib


def _current_task_status(workdir) -> str:
    """当前任务状态（task_state.json）——修正最后一轮偏旧的 pending 显示。"""
    try:
        from wuxing.state import load_state
        st = load_state(pathlib.Path(workdir) / "task_state.json")
    except Exception:  # 简报是展示层，读不到不造假
        return ""
    return str(getattr(st, "status", "") or "")


def build_brief(workdir, conversation_path, *, max_rounds: int = 6,
                max_chars: int = 2500) -> dict:
    """-> {"available","source_session","rounds","brief"}（缺文件 → available False）。"""
    from wuxing.conversation import ConversationState
    path = pathlib.Path(conversation_path)
    if not path.is_file():
        return {"available": False, "source_session": path.name,
                "rounds": 0, "brief": ""}
    state = ConversationState(path)
    turns = list(state.turns)
    # G7：压缩行不渲染；被压缩轮次不列入承接简报（与上下文注入一致）
    comp = state.last_compaction()
    covered = int(comp.get("to_round") or 0) if comp is not None else 0
    turns = [t for t in turns
             if str(t.get("type") or "") != "compaction"
             and not (covered and int(t.get("round") or 0) <= covered)]
    recent = turns[-max_rounds:] if max_rounds > 0 else turns
    last_turn = recent[-1] if recent else None
    current_status = _current_task_status(workdir)
    lines = [f"[新会话承接简报]（来源：{path.name} · 共 {len(turns)} 轮）", "",
             "## 最近轮次"]
    for t in recent:
        rnd = t.get("round", "?")
        text = " ".join(str(t.get("user_text") or "").split())
        if len(text) > 120:
            text = text[:120] + "…"
        item = f"- 第{rnd}轮：{text}" if text else f"- 第{rnd}轮"
        summary = " ".join(str(t.get("summary") or "").split())
        # 真测观察修正：确认/续跑不改轮次记录——最后一轮状态段原为 pending 时
        # 以 task_state 当前状态展示（保留「；交付物 …」余部；历史轮不回溯）
        if (t is last_turn and current_status and current_status != "pending"
                and summary.split("；", 1)[0] == "pending"):
            rest = ("；" + summary.split("；", 1)[1]
                    if "；" in summary else "")
            summary = current_status + rest
        if summary:
            item += f"（{summary[:80]}）"
        arts = [str(a) for a in (t.get("artifacts") or [])]
        if arts:
            item += f"；产物：{', '.join(arts[:4])}"
        lines.append(item)
    all_arts: list[str] = []
    for t in turns:
        for a in (t.get("artifacts") or []):
            s = str(a)
            if s and s not in all_arts:
                all_arts.append(s)
    if all_arts:
        lines += ["", "## 产物清单", *(f"- {a}" for a in all_arts[:10])]
    from wuxing import map_doc
    dg = map_doc.digest(workdir, max_chars=600)
    if dg:
        lines += ["", "## 工作区地图摘要", dg]
    lines += ["", "## 继续指令",
              "请在以上承接背景下继续推进；补充本轮具体目标后发送："]
    brief = "\n".join(lines)
    if len(brief) > max_chars:
        brief = brief[:max_chars].rstrip() + "\n…（承接简报已截断）"
    return {"available": True, "source_session": path.name,
            "rounds": len(turns), "brief": brief}
