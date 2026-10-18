"""确认门文案统一模块（重大优化清单 #2 · 架构 A′）。

- 输出结构化四要素 `view` 随事件进壳（`ConfirmDto.view`），壳侧统一渲染；
- 固定句子集中在 `TEMPLATES`（禁词 lint 的扫描对象）；动态参数单独注入；
- 纪律：通俗优先（禁术语进正文）、不欺骗（风险显性）、未知触发 loud（不静默回退）。
"""
from __future__ import annotations

BANNED_TERMS = ("碎片", "单元", "域", "指纹", "准入", "阈值", "溯源", "DAG", "进程")

# 禁词子串豁免：人话常用复合词（不属于内部术语面）
ALLOWED_COMPOUNDS = ("局域网", "区域", "地域", "领域")

TEMPLATES: dict[str, dict[str, str]] = {
    "unit_confirm": {
        "title": "有一个步骤需要你点头后才会继续。",
        "allow": "允许后：这一步会按计划执行。",
        "deny": "拒绝后：这一步会被标记为「已驳回」，依赖它的后续步骤不会继续。",
        "hint": "看不准就先展开「技术细节」再决定；拿不准时，拒绝是安全的。",
        "trigger.domain_policy": "为什么问你：这类步骤按策略默认由你把关。",
        "trigger.threshold": "为什么问你：这一步按确认设置需要人工把关。",
        "trigger.session_switch": "为什么问你：会话上下文已到切换窗口，继续前需要你确认。",
        "trigger.recovered": "为什么问你：这是上次未完成的确认（恢复态）。",
        "position": "任务位置：共 {total} 步，这是第 {index} 步。",
        "object": "涉及内容：{summary}",
        "object_fallback": "涉及内容：本任务中的一个步骤。",
    },
    "browser_access": {
        "loopback": "内置浏览器要访问本机地址 {address}。{who}",
        "lan": "内置浏览器要访问局域网地址 {address}（内网设备，可能无鉴权）。",
        "who_occupant": "检测到「{label}」正在监听该地址。",
        "who_unknown": "检测到该地址有程序监听（无法识别具体程序）。",
        "allow": "允许后：浏览器会打开这个地址，页面内容对 AI 可见。",
        "deny": "拒绝后：本次不会访问，AI 会收到拒绝并停止这个操作。",
        "hint": "请确认这是你自己启动或信任的服务。",
        "agent_reason": "（agent 说明：{reason}——AI 提供，未核实）",
    },
}


def unit_confirm_view(*, impact: dict | None = None,
                      trigger: str = "domain_policy",
                      index: int | None = None,
                      total: int | None = None) -> dict:
    """单元确认四要素视图（壳侧统一渲染；details 为折叠区技术信息）。"""
    t = TEMPLATES["unit_confirm"]
    key = f"trigger.{trigger}"
    if key not in t:
        raise KeyError(f"unknown confirm trigger: {trigger}")   # loud（禁静默回退）
    imp = dict(impact or {})
    summary = str(imp.get("summary") or "").strip()
    view = {
        "title": t["title"],
        "object": (t["object"].format(summary=summary) if summary
                   else t["object_fallback"]),
        "allow_effect": t["allow"],
        "deny_effect": t["deny"],
        "action_hint": t["hint"],
        "trigger": t[key],
        "position": "",
        "details": {
            "tools": [str(x) for x in (imp.get("tools") or [])],
            "depends": [str(x) for x in (imp.get("depends") or [])],
            "deliverables": [str(x) for x in (imp.get("deliverables") or [])],
            "summary": summary,
        },
        "options": ["批准", "驳回"],
    }
    if isinstance(index, int) and isinstance(total, int) and total > 0 \
            and 1 <= index <= total:
        view["position"] = t["position"].format(index=index, total=total)
    return view


def browser_access_view(*, address: str, source: str = "loopback",
                        occupant_label: str = "",
                        occupant_unknown: bool = False,
                        agent_reason: str = "") -> dict:
    """浏览器访问确认载荷（问题卡承载：title 拼接四要素，≤200 字符）。"""
    t = TEMPLATES["browser_access"]
    if source == "lan":
        head = t["lan"].format(address=address)
    else:
        who = ""
        if occupant_label:
            who = t["who_occupant"].format(label=occupant_label)
        elif occupant_unknown:
            who = t["who_unknown"]
        head = t["loopback"].format(address=address, who=who)
    title = " ".join([head, t["allow"], t["deny"], t["hint"]])
    reason = str(agent_reason or "").strip()
    if reason:
        title += t["agent_reason"].format(reason=reason[:60])
    if len(title) > 200:
        title = title[:199] + "…"
    return {"title": title, "options": ["允许访问", "拒绝"]}
