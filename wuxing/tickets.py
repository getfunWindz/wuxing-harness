"""实施票据（二期批 4 · 设计 §8）：工作区级执行清单（append-only jsonl + 读侧归并）。

文件：`<workdir>/.wuxing/tickets.jsonl`——事件式：
  {"event": "created", "ticket": {...}, "ts": …}
  {"event": "updated", "id": "T-1", "patch": {...}, "ts": …}
纪律：损坏行跳过（韧性）；写侧单引擎串行 append；票据是临时物（验收后可清理，
地图/决策记录是长期权威）。
"""
from __future__ import annotations

import json
import pathlib
import re
import time

from wuxing.filelock import lock_for

STATUSES = ("proposed", "ready", "running", "done", "failed", "cancelled")
_FIELDS = ("title", "goal", "acceptance", "deps", "spec", "artifacts",
           "fragment_ids", "error", "status", "claimed_by", "claimed_at")
_TERMINAL = ("done", "failed", "cancelled")


class TicketClaimedError(RuntimeError):
    """票据已被他人认领（G8）；holder 为持有者（会话名/cli）。"""

    def __init__(self, ticket_id: str, holder: str):
        super().__init__(f"票据 {ticket_id} 已被 {holder} 认领")
        self.ticket_id = str(ticket_id)
        self.holder = str(holder)


def tickets_path(workdir) -> pathlib.Path:
    return pathlib.Path(workdir) / ".wuxing" / "tickets.jsonl"


def _append(workdir, row: dict) -> None:
    p = tickets_path(workdir)
    with lock_for(p):
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def load(workdir) -> list[dict]:
    """归并最新状态（按首个 created 顺序；损坏行/未知 id 的 updated 跳过）。"""
    p = tickets_path(workdir)
    if not p.is_file():
        return []
    out: list[dict] = []
    index: dict[str, dict] = {}
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("event") == "created" and isinstance(row.get("ticket"), dict):
            t = dict(row["ticket"])
            if str(t.get("id") or ""):
                out.append(t)
                index[str(t["id"])] = t
        elif row.get("event") == "updated":
            t = index.get(str(row.get("id") or ""))
            if t is not None and isinstance(row.get("patch"), dict):
                t.update(row["patch"])
        elif row.get("event") == "claimed":
            t = index.get(str(row.get("id") or ""))
            if t is not None:
                t["claimed_by"] = str(row.get("by") or "")
                t["claimed_at"] = row.get("ts")
        elif row.get("event") in ("unclaimed", "released"):
            t = index.get(str(row.get("id") or ""))
            if t is not None:
                t.pop("claimed_by", None)
                t.pop("claimed_at", None)
    return out


def find(workdir, tid: str):
    tid = str(tid or "")
    return next((t for t in load(workdir) if t.get("id") == tid), None)


def create(workdir, *, title, goal="", acceptance=None, deps=None, spec="",
           status="proposed") -> dict:
    """新建票据（T-n 顺序分配）；未知依赖 → ValueError（早报）。"""
    existing = load(workdir)
    used = [int(t["id"][2:]) for t in existing
            if str(t.get("id") or "").startswith("T-") and t["id"][2:].isdigit()]
    deps_list = [str(d) for d in (deps or [])]
    known = {str(t["id"]) for t in existing}
    unknown = [d for d in deps_list if d not in known]
    if unknown:
        raise ValueError(f"未知依赖票据：{unknown}")
    t = {"id": f"T-{max(used) + 1 if used else 1}", "title": str(title or ""),
         "goal": str(goal or ""),
         "acceptance": [str(a) for a in (acceptance or [])],
         "deps": deps_list, "status": str(status or "proposed"),
         "spec": str(spec or ""), "artifacts": [], "fragment_ids": [],
         "error": "", "ts": round(time.time(), 3)}
    _append(workdir, {"event": "created", "ticket": t, "ts": t["ts"]})
    return t


def update(workdir, tid: str, patch: dict) -> dict | None:
    """追加更新事件（白名单字段；未知 id → None——不静默造票）。

    低层原语（Q3 决策 b）：不做迁移校验（直写白名单字段）；状态迁移纪律由
    操作层承担——publish（proposed→ready）/ reset（终态→ready）/ 回写
    （running→done/failed）；强约束表见 `wuxing/state_machine.py`，守卫测试
    `test_operation_layer_transitions_stay_in_table`。

    G8：写入终态（done/failed/cancelled）时自动释放认领（追加 ``released`` 事件，
    历史保留）。
    """
    with lock_for(tickets_path(workdir)):
        t = find(workdir, tid)
        if t is None:
            return None
        clean = {k: patch[k] for k in _FIELDS if k in patch}
        _append(workdir, {"event": "updated", "id": str(tid), "patch": clean,
                          "ts": round(time.time(), 3)})
        t.update(clean)
        if (str(clean.get("status") or "") in _TERMINAL
                and t.get("claimed_by")):
            _append(workdir, {"event": "released", "id": str(tid),
                              "reason": str(clean.get("status")),
                              "ts": round(time.time(), 3)})
            t.pop("claimed_by", None)
            t.pop("claimed_at", None)
        return t


def claim(workdir, tid: str, *, by: str) -> dict | None:
    """认领票据（G8）；未知 id → None；他人已认领 → TicketClaimedError；
    同人重复认领幂等；终态票据拒绝认领。"""
    by = str(by or "").strip() or "cli"
    with lock_for(tickets_path(workdir)):
        t = find(workdir, tid)
        if t is None:
            return None
        if str(t.get("status") or "") in _TERMINAL:
            raise ValueError(
                f"终态票据不可认领：{tid}（{t.get('status')}）")
        holder = str(t.get("claimed_by") or "")
        if holder == by:
            return t
        if holder:
            raise TicketClaimedError(str(tid), holder)
        _append(workdir, {"event": "claimed", "id": str(tid), "by": by,
                          "ts": round(time.time(), 3)})
        t["claimed_by"] = by
        t["claimed_at"] = round(time.time(), 3)
        return t


def unclaim(workdir, tid: str, *, by: str = "", reason: str = "") -> dict | None:
    """释放认领（手动/用户确认路径）；无认领幂等；未知 id → None。"""
    with lock_for(tickets_path(workdir)):
        t = find(workdir, tid)
        if t is None:
            return None
        if not t.get("claimed_by"):
            return t
        _append(workdir, {"event": "unclaimed", "id": str(tid),
                          "by": str(by or ""), "reason": str(reason or ""),
                          "ts": round(time.time(), 3)})
        t.pop("claimed_by", None)
        t.pop("claimed_at", None)
        return t


def claim_many(workdir, ids, *, by: str, force: bool = False) -> list[dict]:
    """批量认领（G8-M2，原子）：任一冲突 → 全部不认领（除非 force 强制移交）。

    预检全部可认领后再写入——不留半认领状态；未知/终态票据 → ValueError（早报）。
    force=True（人工裁决出口/提交期 claim_override）：先取消旧认领再占为己有。
    """
    by = str(by or "").strip() or "cli"
    wanted = [str(i) for i in (ids or []) if str(i)]
    if not wanted:
        return []
    with lock_for(tickets_path(workdir)):
        all_t = {str(t["id"]): t for t in load(workdir)}
        for tid in wanted:
            t = all_t.get(tid)
            if t is None:
                raise ValueError(f"未知票据：{tid}")
            if str(t.get("status") or "") in _TERMINAL:
                raise ValueError(f"终态票据不可认领：{tid}")
            holder = str(t.get("claimed_by") or "")
            if holder and holder != by and not force:
                raise TicketClaimedError(tid, holder)
        out: list[dict] = []
        for tid in wanted:
            t = all_t[tid]
            holder = str(t.get("claimed_by") or "")
            if holder == by:
                out.append(t)
                continue
            if holder and force:
                unclaim(workdir, tid, by=by, reason="override")
            claim(workdir, tid, by=by)
            out.append(find(workdir, tid))
        return out


def ready_ids(workdir) -> list[str]:
    """就绪票据（G8）：status=ready + 依赖全 done + 未认领（执行面 frontier）。"""
    all_t = load(workdir)
    done = {str(t.get("id")) for t in all_t
            if str(t.get("status") or "") == "done"}
    out: list[str] = []
    for t in all_t:
        if str(t.get("status") or "") != "ready":
            continue
        if t.get("claimed_by"):
            continue
        if all(str(d) in done for d in (t.get("deps") or [])):
            out.append(str(t["id"]))
    return out


def claims(workdir) -> list[dict]:
    """活动认领视图（G8）：``[{id, by, at, age_s}]``。"""
    now = time.time()
    out: list[dict] = []
    for t in load(workdir):
        by = str(t.get("claimed_by") or "")
        if not by:
            continue
        at = float(t.get("claimed_at") or 0.0)
        out.append({"id": str(t.get("id") or ""), "by": by, "at": at,
                    "age_s": round(now - at, 1) if at else None})
    return out


def annotate_claims(items, active_holders=(), *, now=None) -> list[dict]:
    """票据列表附认领元数据（G8-M3 壳面）：stale = 认领者无活动 run 支撑。

    仅展示层计算（不改票据事实）；`claimed_age_s` 为认领时长（秒）。
    """
    now = time.time() if now is None else now
    holders = {str(h) for h in (active_holders or ())}
    out: list[dict] = []
    for t in (items or ()):
        item = dict(t)
        by = str(t.get("claimed_by") or "")
        item["stale"] = bool(by) and by not in holders
        item["claimed_age_s"] = (round(now - float(t.get("claimed_at") or 0), 1)
                                 if by and t.get("claimed_at") else None)
        out.append(item)
    return out


def claims_note(workdir, *, stale_after_s: float = 3600.0) -> str:
    """认领注记（设计轮上下文注入）：有认领时返回 ``[票据认领]`` 块。

    包含持有时长与「可能陈旧」标记——由 agent 向用户确认后经 ``unclaim_ticket`` 释放。
    """
    items = claims(workdir)
    if not items:
        return ""
    lines = ["[票据认领]（无对应活动任务的属陈旧——请向用户确认是否清除）"]
    for it in items:
        age = it.get("age_s")
        if isinstance(age, (int, float)):
            age_txt = f"{age / 3600:.1f}h"
            stale = age >= stale_after_s
        else:
            age_txt, stale = "?", False
        lines.append(f"- {it['id']} 由 {it['by']} 认领（{age_txt}）"
                     + ("【可能陈旧】" if stale else ""))
    return "\n".join(lines)


def validate_deps(tickets) -> None:
    """未知依赖/环 → ValueError（发布期硬校验——依赖图必须可拓扑）。"""
    known = {str(t.get("id")) for t in tickets}
    graph = {str(t.get("id")): [str(d) for d in (t.get("deps") or [])]
             for t in tickets}
    for tid, deps in graph.items():
        unknown = [d for d in deps if d not in known]
        if unknown:
            raise ValueError(f"票据 {tid} 依赖未知票据：{unknown}")
    color: dict[str, int] = {}

    def dfs(node: str) -> None:
        color[node] = 1
        for nxt in graph.get(node, []):
            if color.get(nxt) == 1:
                raise ValueError(f"票据依赖成环：{node} → {nxt}")
            if color.get(nxt, 0) == 0:
                dfs(nxt)
        color[node] = 2

    for tid in graph:
        if color.get(tid, 0) == 0:
            dfs(tid)


def _ticket_of(fragment_id: str) -> str:
    """碎片 id → 票据 id（F-T1 / F-T1-v → T-1；否则空）。"""
    fid = str(fragment_id or "")
    if not fid.startswith("F-T"):
        return ""
    body = fid[2:]
    body = body.removesuffix("-v")
    return f"T-{body[1:]}" if re.fullmatch(r"T\d+", body) else ""


def to_fragments(tickets_list, spec_text: str = "") -> list[dict]:
    """票据 → 碎片 DAG（批 5）：每票 1 execute + 1 verify；依赖边→依赖票 verify 碎片。

    `spec_text` 摘要注入各票 execute 文本（截断 1200 字符——防注入膨胀）。
    """
    out: list[dict] = []
    for t in tickets_list:
        tid = str(t["id"])
        n = tid.removeprefix("T-")
        acc = "\n".join(f"- {a}" for a in (t.get("acceptance") or []))
        head = f"票据 {tid}：{t.get('title')}\n目标：{t.get('goal')}"
        spec = str(spec_text or "")[:1200]
        body = head + (f"\n验收标准：\n{acc}" if acc else "")
        if spec:
            body += f"\n\n[规格摘要]\n{spec}"
        deps = [f"F-T{str(d)[2:]}-v" for d in (t.get("deps") or [])]
        exec_frag = {"fragment_id": f"F-T{n}", "domain": "execute",
                     "deps": deps, "deliverables": [], "text": body,
                     "ticket": tid}
        if deps:
            # 真测裁决 W3：依赖票验收通过才开工（上游 verify ok 且非 verdict_fail）
            exec_frag["require_ok_deps"] = True
        out.append(exec_frag)
        out.append({"fragment_id": f"F-T{n}-v", "domain": "verify",
                    "deps": [f"F-T{n}"], "deliverables": [],
                    "text": f"验收票据 {tid}：{t.get('title')}\n验收标准：\n{acc}",
                    "ticket": tid})
    return out


def publish(workdir, ids=None) -> list[dict]:
    """proposed → ready（ids 缺省=全部 proposed；显式 [] → 不发布）。

    发布前依赖图校验（含环）。显式指定的票据必须为 proposed——
    done/failed/running 不得被重置为 ready（状态机纪律，审查 F2）。
    """
    all_t = load(workdir)
    validate_deps(all_t)
    if ids is None:
        picked = {str(t["id"]) for t in all_t if t.get("status") == "proposed"}
    else:
        picked = {str(i) for i in ids}
        unknown = [i for i in picked
                   if not any(str(t["id"]) == i for t in all_t)]
        if unknown:
            raise ValueError(f"未知票据：{unknown}")
        not_proposed = [str(t["id"]) for t in all_t
                        if str(t["id"]) in picked
                        and t.get("status") != "proposed"]
        if not_proposed:
            raise ValueError(f"仅 proposed 票据可发布：{not_proposed}")
    for t in all_t:
        if str(t["id"]) in picked:
            update(workdir, str(t["id"]), {"status": "ready"})
    return load(workdir)


def reset(workdir, ids=None) -> list[dict]:
    """重置票据（失败票重跑）→ ready + 依赖闭包（真测裁决 W4.5）。

    背景：部分重跑时 deps 指向未激活票据 → to_fragments 悬空依赖；
    当时靠手工「一并激活」规避。reset 把闭包自动化：
      - ids 缺省 = 全部 failed/cancelled；显式 ids 必须存在；
      - 允许 failed/cancelled/done → ready（done = 显式重验）；
        拒绝 running（忙）与 proposed（须先过发布状态机）；
      - deps 中 failed/cancelled 递归纳入（下游 require_ok_deps 需其验收通过）；
        done 依赖视为外部已完成（执行期按验收通过声明，不重置）；
      - 清理旧轮残留（error/fragment_ids/artifacts）。
    """
    all_t = load(workdir)
    index = {str(t["id"]): t for t in all_t}
    if ids is None:
        picked = {tid for tid, t in index.items()
                  if t.get("status") in ("failed", "cancelled")}
    else:
        picked = {str(i) for i in ids}
        unknown = sorted(i for i in picked if i not in index)
        if unknown:
            raise ValueError(f"未知票据：{unknown}")
    closure: set[str] = set()
    stack = list(picked)
    while stack:
        tid = stack.pop()
        if tid in closure:
            continue
        t = index[tid]
        st = str(t.get("status") or "")
        if st == "running":
            raise ValueError(f"票据 {tid} 正在执行，不能重置（先等待/取消）")
        if st == "proposed":
            raise ValueError(f"票据 {tid} 尚未发布（proposed）——请先发布")
        closure.add(tid)
        for d in (t.get("deps") or []):
            dep = index.get(str(d))
            if dep is not None and str(dep.get("status") or "") in (
                    "failed", "cancelled"):
                stack.append(str(d))
    for tid in sorted(closure):
        update(workdir, tid, {"status": "ready", "error": "",
                              "fragment_ids": [], "artifacts": []})
    return load(workdir)
