"""循迹设计态（双模式批 3 · 设计 §5.2/§5.3）。

文件：`<workdir>/.wuxing/design-state.json`（原子写；缺失/损坏 → {}——读侧容错）。
键：version/session/phase/round/questions[{"q","recommend"}]/facts[]/map_path/
    map_hash/updated_at。软约束（问题数/轮数上限）不入状态——由提示词与壳呈现。
"""
from __future__ import annotations

import json
import pathlib
import re
import time

from wuxing.atomic_write import atomic_write_text
from wuxing.filelock import lock_for

PHASES = ("recon", "grilling", "map", "ready")


def state_path(workdir) -> pathlib.Path:
    return pathlib.Path(workdir) / ".wuxing" / "design-state.json"


def load(workdir) -> dict:
    p = state_path(workdir)
    with lock_for(p):
        if not p.is_file():
            return {}
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}


def save(workdir, patch: dict) -> dict:
    """合并写（给定键覆盖；version/updated_at 自动）——原子替换。

    G8-M2：读改写整体入路径级锁——多 Engine 实例并发 save 不丢字段。
    """
    p = state_path(workdir)
    with lock_for(p):
        data = load(workdir)
        data.setdefault("version", 1)
        for k, v in (patch or {}).items():
            data[k] = v
        data["updated_at"] = round(time.time(), 3)
        atomic_write_text(p,
                          json.dumps(data, ensure_ascii=False, indent=2))
        return data


DRIFT_CAP = 20


def merge_drift(prev, entries, cap: int = DRIFT_CAP) -> list[dict]:
    """合并漂移记录（C5）：最近窗口；同 (round, kind, id) 后写覆盖（防重复堆积）。"""
    out = [d for d in (prev or []) if isinstance(d, dict)]
    for e in entries or []:
        if not isinstance(e, dict):
            continue
        key = (e.get("round"), e.get("kind"), str(e.get("id") or ""))
        out = [d for d in out
               if (d.get("round"), d.get("kind"),
                   str(d.get("id") or "")) != key]
        out.append(e)
    return out[-int(cap):]


def _block(text: str, header: str) -> str:
    """取块正文（到下一个行首【…】块或文末）。

    真测 REAL-9：rfind 会被完成声明里的「【决策】块」prose 提及劫持——
    改为：行首锚定的**首次**出现优先；无行首块才回退首次出现（单行容错）；
    块尾同样行首锚定（防块内正文含【字符被误截）。
    """
    src = str(text or "")
    starts = [m.start() for m in
              re.finditer(r"(?m)^[ \t]*" + re.escape(header), src)]
    if starts:
        start = starts[0]
    else:
        idx = src.find(header)
        if idx < 0:
            return ""
        start = idx
    body = src[start + len(header):]
    nxt = re.search(r"(?m)^[ \t]*【", body)
    if nxt is not None:
        return body[:nxt.start()]
    pos = body.find("【")
    return body[:pos] if pos >= 0 else body


def parse_questions(text) -> list[dict]:
    """【问题】块 → [{"q","recommend","blocked_by"}]。

    `（推荐：…）`/`(推荐: …)` 与 `（依赖：Q-1,Q-2）` 容错（各占独立括号）。
    """
    out: list[dict] = []
    for line in _block(str(text or ""), "【问题】").splitlines():
        line = line.strip()
        m = re.match(r"^\d+[.、)]\s*(.+)$", line)
        if not m:
            continue
        body = m.group(1).strip()
        blocked: list[str] = []
        dm = re.search(r"[（(]\s*依赖[：:]\s*(.*?)\s*[）)]\s*$", body)
        if dm:
            blocked = [x.strip() for x in re.split(r"[，,、\s]+", dm.group(1))
                       if re.fullmatch(r"Q-\d+", x.strip())]
            body = body[:dm.start()].strip()
        rec = ""
        rm = re.search(r"[（(]\s*推荐[：:]\s*(.*?)\s*[）)]\s*$", body)
        if rm:
            rec = rm.group(1).strip()
            body = body[:rm.start()].strip()
        if body:
            out.append({"q": body, "recommend": rec, "blocked_by": blocked})
    return out


def parse_facts(text) -> list[str]:
    """【事实】块 → 事实行（`-`/`*`/数字前缀剥离）。"""
    out: list[str] = []
    for line in _block(str(text or ""), "【事实】").splitlines():
        line = line.strip()
        m = re.match(r"^(?:[-*]|\d+[.、)])\s*(.+)$", line)
        if m and m.group(1).strip():
            out.append(m.group(1).strip())
    return out


def parse_decisions(text) -> list[dict]:
    """【决策】块 → [{"ticket","text","why","rollback"}]（`｜` 分隔；容错）。

    行形如：`- Q-2：<决策>｜理由：<理由>｜回滚：D-1`（ticket/理由/回滚可省）。
    """
    out: list[dict] = []
    for line in _block(str(text or ""), "【决策】").splitlines():
        line = line.strip()
        m = re.match(r"^(?:[-*]|\d+[.、)])\s*(.+)$", line)
        if not m:
            continue
        segs = [x.strip() for x in m.group(1).split("｜")]
        first, ticket = (segs[0] if segs else ""), ""
        tm = re.match(r"^(Q-\d+)\s*[：:]\s*(.+)$", first)
        if tm:
            ticket, first = tm.group(1), tm.group(2).strip()
        elif re.match(r"^Q-\d+\s*[/、,，]", first):
            continue  # 真测 REAL-9：状态汇总行（如「Q-1/Q-2/Q-3 已关闭…」）不是决策
        item = {"ticket": ticket, "text": first, "why": "", "rollback": ""}
        for seg in segs[1:]:
            if seg.startswith("理由："):
                item["why"] = seg[len("理由："):].strip()
            elif seg.startswith("回滚："):
                val = seg[len("回滚："):].strip()
                item["rollback"] = val if re.fullmatch(r"D-\d+", val) else ""
        if item["text"]:
            out.append(item)
    return out


def parse_tickets(text) -> list[dict]:
    """【票据】块 → [{"title","goal","acceptance":[…],"deps":[…]}）（容错）。

    行形如：`- 切片一｜目标：…｜验收：甲；乙｜依赖：T-1,T-2`（字段可省）。
    """
    out: list[dict] = []
    for line in _block(str(text or ""), "【票据】").splitlines():
        line = line.strip()
        m = re.match(r"^(?:[-*]|\d+[.、)])\s*(.+)$", line)
        if not m:
            continue
        segs = [x.strip() for x in m.group(1).split("｜")]
        item = {"title": segs[0] if segs else "", "goal": "",
                "acceptance": [], "deps": []}
        for seg in segs[1:]:
            if seg.startswith("目标："):
                item["goal"] = seg[len("目标："):].strip()
            elif seg.startswith("验收："):
                item["acceptance"] = [x.strip() for x in
                                      re.split(r"[；;]", seg[len("验收："):])
                                      if x.strip()]
            elif seg.startswith("依赖："):
                item["deps"] = [x.strip() for x in
                                re.split(r"[，,、\s]+", seg[len("依赖："):])
                                if re.fullmatch(r"T-\d+", x.strip())]
        if item["title"]:
            out.append(item)
    return out


def tickets(state) -> list[dict]:
    """open 决策票据（结构合法者——损坏条目跳过）。"""
    out = []
    for t in (state or {}).get("decision_tickets") or []:
        if isinstance(t, dict) and str(t.get("id") or ""):
            out.append(t)
    return out


def frontier_ids(state) -> set:
    """frontier：blocked_by 与 open 集合无交集的开放票据。"""
    tks = tickets(state)
    open_ids = {str(t.get("id")) for t in tks}
    return {str(t["id"]) for t in tks
            if not (set(map(str, t.get("blocked_by") or [])) & open_ids)}


def infer_phase(workdir, *, session: str = "", turns: int = 0) -> tuple[str, bool]:
    """损坏/缺失恢复：地图可用 → map；有轮次 → grilling；否则 recon（inferred=True）。"""
    from wuxing.map_doc import is_usable
    if is_usable(workdir):
        return "map", True
    if int(turns or 0) > 0:
        return "grilling", True
    return "recon", True


def brief(workdir, state: dict | None = None) -> str:
    """设计轮提示词上下文块（当前阶段/未决问题/事实/地图指针）。"""
    st = state if state is not None else load(workdir)
    from wuxing.map_doc import file_hash, is_usable, map_path
    mp = map_path(workdir)
    lines = ["[循迹设计态]"]
    lines.append(f"阶段：{st.get('phase') or 'recon'}；轮次：{st.get('round') or 0}")
    if st.get("branch_head"):
        lines.append(f"现行决策头：{st.get('branch_head')}"
                     "（回滚口径：上游指该 id）")
    tks = tickets(st)
    qs = st.get("questions") or []
    if tks:
        fr = frontier_ids(st)
        lines.append("决策票据（回答后在【决策】块按 id 关闭；关闭即入地图、用完即弃）：")
        for t in tks[:8]:
            rec = f"（推荐：{t.get('recommend')}）" if t.get("recommend") else ""
            dep = t.get("blocked_by") or []
            dep_s = f"［依赖：{'，'.join(map(str, dep))}］" if dep else ""
            mark = "" if str(t["id"]) in fr else "（待前置）"
            lines.append(f"- [{t['id']}]{mark}{dep_s} {t.get('statement')}{rec}")
    elif qs:
        lines.append("未决问题：")
        for i, q in enumerate(qs[:8], 1):
            rec = f"（推荐：{q.get('recommend')}）" if q.get("recommend") else ""
            lines.append(f"{i}. {q.get('q')}{rec}")
    facts = st.get("facts") or []
    drift = [d for d in (st.get("drift") or []) if isinstance(d, dict)]
    if drift:
        lines.append("机械校验（设计流漂移——请先纠正再继续）：")
        for d in drift[-5:]:
            lines.append(f"- [{d.get('kind')}] {d.get('id')}："
                         f"{d.get('detail')}（第 {d.get('round')} 轮）")
    if facts:
        lines.append("已知事实：" + "；".join(str(f) for f in facts[:8]))
    spec_slug = str(st.get("spec_slug") or "")
    spec_path = str(st.get("spec_path") or "")
    if spec_slug:
        lines.append(f"规格已生成：{spec_path or spec_slug}"
                     "（如需修订，用户确认后重调 write_spec；可继续交给执行）")
    elif is_usable(workdir) and not tks:
        lines.append("票据已全部关闭且地图就绪：可合成规格——用户确认后调用 "
                     "write_spec（七段；不写文件路径与代码片段）")
    from wuxing.tickets import load as _load_impl
    _impl = _load_impl(workdir)
    _ready = [t for t in _impl if t.get("status") == "ready"]
    _prop = [t for t in _impl if t.get("status") == "proposed"]
    if spec_slug and not _ready:
        if _prop:
            lines.append("实施票据待发布：" + "；".join(
                f"{t['id']} {t['title']}" for t in _prop)[:200]
                + "（用户在设计卡片发布后交给执行）")
        else:
            lines.append("规格已就绪：可提议实施票据（【票据】块：垂直切片/"
                         "目标/验收标准/依赖边；用户 quiz 后发布）")
    elif _ready:
        lines.append("实施票据已发布：" + "；".join(
            f"{t['id']} {t['title']}" for t in _ready)[:200] + "（可交给执行）")
    if is_usable(workdir):
        lines.append(f"地图已就绪：WUXING.md（hash {file_hash(mp)[:12]}）——"
                     "如信息已完备，可提示用户交接执行；如需修订，调用 write_map。")
    else:
        lines.append("地图未就绪：WUXING.md（尚未创建）——信息充分且用户确认后调用 write_map。")
    return "\n".join(lines)
