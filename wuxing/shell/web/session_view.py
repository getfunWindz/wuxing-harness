"""工作区域读取聚合（轮次化/碎片会话/轨迹）。

只读消费（不新增写入）：
  - .wuxing/<conversation>.jsonl   会话轮次
  - .wuxing/provenance.jsonl       碎片（unit/goal/domain/status/ts）
  - .wuxing/trace.jsonl            单元时长/工具数/session 元数据
  - .wuxing/sessions/*.jsonl       碎片会话存档

纪律：
  - 损坏行跳过（韧性惯例）；缺文件返回空（容错）
  - 路径穿越拒绝（unit 名白名单 + 目录约束）
  - 不 import 引擎内部模块（AST 白名单：engine/events/shell.protocol）
    ——task_hash8 与 wuxing.provenance.task_hash 同口径，由单测跨模块冻结
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re

_UNIT_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_PARALLEL_EPS = 0.05  # 区间重叠阈值（秒）——防浮点噪声


def task_hash8(text: str) -> str:
    """与 wuxing.provenance.task_hash 同口径（sha256 前 8 位）。"""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:8]


def read_jsonl(path: pathlib.Path, limit: int | None = None) -> list[dict]:
    """读 jsonl（损坏行跳过；limit=尾部截取）。"""
    path = pathlib.Path(path)
    if not path.is_file():
        return []
    rows: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue  # 损坏行跳过
    except OSError:
        return []
    return rows[-limit:] if limit else rows


# ---- 轮次/碎片 join（Task 1.2） ----

def _session_file_name(sess_dir: pathlib.Path, uid: str, round_no) -> str:
    """碎片会话文件名（优先本轮前缀；否则取最新前缀文件；再退裸名）。

    引擎命名：`{run_start_round_no}-{unit_id}.jsonl`（0 → 裸名）——
    读取侧对前缀做数值感知降序回退（真实数据前缀常为 N-1）。
    """
    if not uid:
        return ""
    try:
        rn = int(round_no)
    except (TypeError, ValueError):
        rn = 0
    cands = ([f"{rn}-{uid}.jsonl"] if rn > 0 else [])

    def _prefix(name: str) -> int:
        head = name.split("-", 1)[0]
        return int(head) if head.isdigit() else -1

    prefixed = sorted((p.name for p in sess_dir.glob(f"*-{uid}.jsonl")),
                      key=_prefix, reverse=True)
    cands += [n for n in prefixed if n not in cands]
    cands.append(f"{uid}.jsonl")
    for name in cands:  # 优先本轮精确文件，其次最新前缀，最后裸名
        if (sess_dir / name).is_file():
            return name
    return ""


def _trace_for(frag_rows: list[dict], trace_rows: list[dict],
               lo: float, hi: float) -> dict:
    """窗口 (lo, hi] 内按 unit 配对 trace：时长/工具数/session 元数据/并行标记。"""
    uids = {str(f.get("unit_id") or "") for f in frag_rows}
    info: dict[str, dict] = {}
    for row in trace_rows:
        uid = str(row.get("unit_id") or "")
        if uid not in uids:
            continue
        ts = float(row.get("ts") or 0)
        if not (lo < ts <= hi):
            continue
        event = str(row.get("event") or "")
        cur = info.setdefault(uid, {"_start": None, "_end": None, "tools": 0,
                                    "key": "", "reuse": 0, "chars": 0})
        if event == "unit_started" and cur["_start"] is None:
            cur["_start"] = ts
        elif event == "unit_done":
            cur["_end"] = ts
        elif event == "tool_call":
            cur["tools"] += 1
        elif event == "session_created":
            cur["key"] = str(row.get("key") or "")
            cur["reuse"] = int(row.get("reuse") or 0)
            cur["chars"] = int(row.get("session_chars") or 0)
    # 并行判定：存在区间重叠的碎片对（两两；缺失区间的碎片不参与）
    pairs = [(u, c) for u, c in info.items()
             if c["_start"] is not None and c["_end"] is not None]
    for i in range(len(pairs)):
        for j in range(i + 1, len(pairs)):
            c1 = pairs[i][1]
            c2 = pairs[j][1]
            if (c1["_start"] < c2["_end"] - _PARALLEL_EPS
                    and c2["_start"] < c1["_end"] - _PARALLEL_EPS):
                c1["parallel"] = True
                c2["parallel"] = True
    return info


def branch_lineage(ws_dir: pathlib.Path) -> dict:
    """G1：分支血缘（`.wuxing/branches.jsonl` → {会话名: 血缘记录}）。

    append-only 流——同名多条取最新（后写覆盖）；损坏行跳过（韧性惯例）。
    """
    path = pathlib.Path(ws_dir) / ".wuxing" / "branches.jsonl"
    out: dict = {}
    for row in read_jsonl(path):
        name = str(row.get("conversation") or "")
        if not name:
            continue
        out[name] = {"source": str(row.get("source") or ""),
                     "from_round": int(row.get("from_round") or 0),
                     "mode": str(row.get("mode") or ""),
                     "summary_mode": str(row.get("summary_mode") or "")}
    return out


def session_rounds(ws_dir: pathlib.Path, name: str) -> dict:
    """会话轮 + 每轮碎片（join：task_hash8 + ts 窗口；并行：区间重叠）。

    窗口消歧：同文本重复任务 → 仅归属 `(上一轮 ts, 本轮 ts]` 内的 provenance 行。
    """
    wux = pathlib.Path(ws_dir) / ".wuxing"
    fname = str(name or "")
    if not fname.endswith(".jsonl"):
        fname = f"{fname}.jsonl"
    conv = read_jsonl(wux / fname)
    prov = read_jsonl(wux / "provenance.jsonl")
    trace = read_jsonl(wux / "trace.jsonl")
    sess_dir = wux / "sessions"
    rounds: list[dict] = []
    prev = -1.0
    for row in conv:
        if "round" not in row and "user_text" not in row:
            continue  # 非轮次行（旧 role/content 形状）——跳过（不渲染空轮次）
        ts = float(row.get("ts") or 0)
        th = task_hash8(str(row.get("user_text") or ""))
        matched = [p for p in prov
                   if str(p.get("task_hash") or "") == th
                   and prev < float(p.get("ts") or 0) <= ts]
        info = _trace_for(matched, trace, prev, ts)
        frags = [_frag(p, info.get(str(p.get("unit_id") or ""), {}),
                       sess_dir, row.get("round")) for p in matched]
        rounds.append({
            "round": int(row.get("round") or 0),
            "user_text": str(row.get("user_text") or ""),
            "summary": str(row.get("summary") or ""),
            "ts": ts,
            "artifacts": [str(a) for a in (row.get("artifacts") or [])],
            "parallel": any(f["parallel"] for f in frags),
            "fragments": frags,
        })
        prev = ts
    return {"name": fname, "rounds": rounds}


# ---- 碎片会话内容 / 轨迹（Task 1.3） ----

def _frag(p: dict, ti: dict, sess_dir: pathlib.Path, round_no) -> dict:
    """碎片 DTO（join 结果单条）。"""
    uid = str(p.get("unit_id") or "")
    start, end = ti.get("_start"), ti.get("_end")
    return {
        "unit_id": uid,
        "domain": str(p.get("domain") or ""),
        "goal": str(p.get("goal") or ""),
        "status": str(p.get("status") or ""),
        "ts": float(p.get("ts") or 0),
        "artifacts": [str(a) for a in (p.get("artifacts") or [])],
        "duration_ms": (round((end - start) * 1000)
                        if start is not None and end is not None else None),
        "tool_calls": int(ti.get("tools") or 0),
        "key": str(ti.get("key") or ""),
        "reuse": int(ti.get("reuse") or 0),
        "session_file": _session_file_name(sess_dir, uid, round_no),
        "parallel": bool(ti.get("parallel", False)),
    }


def _unit_meta(ws_dir: pathlib.Path, uid: str) -> dict:
    """碎片元数据（provenance 最近一条 + trace session_created 最近一条）。"""
    wux = pathlib.Path(ws_dir) / ".wuxing"
    meta = {"domain": "", "status": "", "goal": "", "key": "", "reuse": 0, "chars": 0}
    for p in read_jsonl(wux / "provenance.jsonl"):
        if str(p.get("unit_id") or "") == uid:
            meta["domain"] = str(p.get("domain") or "")
            meta["status"] = str(p.get("status") or "")
            meta["goal"] = str(p.get("goal") or "")
    for t in read_jsonl(wux / "trace.jsonl"):
        if (str(t.get("unit_id") or "") == uid
                and str(t.get("event") or "") == "session_created"):
            meta["key"] = str(t.get("key") or "")
            meta["reuse"] = int(t.get("reuse") or 0)
            meta["chars"] = int(t.get("session_chars") or 0)
    return meta


def unit_session(ws_dir: pathlib.Path, unit: str) -> dict:
    """碎片会话内容（文件列表 + 按文件/ts 排序的 seed/增量行组 + 元数据
    + 绑定轮次（碎片内提交的会话轮——设计 §3.3/§4））。"""
    uid = str(unit or "")
    empty = {"unit_id": "", "files": [], "groups": [], "meta": {},
             "bound_rounds": []}
    if not _UNIT_RE.match(uid):
        return empty  # 非法名/路径穿越 → 空
    base = (pathlib.Path(ws_dir) / ".wuxing" / "sessions").resolve()
    if not base.is_dir():
        return {"unit_id": uid, "files": [], "groups": [], "meta": {},
                "bound_rounds": _bound_rounds(ws_dir, uid)}
    cands = [base / f"{uid}.jsonl"] + sorted(base.glob(f"*-{uid}.jsonl"))
    files = [p.name for p in cands if p.is_file()]
    groups: list[dict] = []
    for p in cands:
        if not p.is_file():
            continue
        for row in read_jsonl(p):
            groups.append({
                "file": p.name,
                "round": int(row.get("round") or 0),
                "state": str(row.get("state") or ""),
                "status": str(row.get("status") or ""),
                "ts": float(row.get("ts") or 0),
                "messages": list(row.get("messages") or []),
            })
    groups.sort(key=lambda g: (g["file"], g["ts"]))
    return {"unit_id": uid, "files": files, "groups": groups,
            "meta": _unit_meta(ws_dir, uid),
            "bound_rounds": _bound_rounds(ws_dir, uid)}


def _bound_rounds(ws_dir: pathlib.Path, uid: str) -> list[dict]:
    """碎片绑定轮次（join unit-bindings.jsonl + conversation 轮次行；设计 §3.3）。

    绑定记录 `{conversation, unit_id, round, ts}` 由壳侧 manager 在碎片内提交
    完成后写入；此处只读聚合（缺失/坏行/被删会话一律跳过）。
    """
    if not uid:
        return []
    wux = pathlib.Path(ws_dir) / ".wuxing"
    out: list[dict] = []
    seen: set[tuple[str, int]] = set()
    for b in read_jsonl(wux / "unit-bindings.jsonl"):
        if str(b.get("unit_id") or "") != uid:
            continue
        conv = str(b.get("conversation") or "")
        if not conv.endswith(".jsonl") or "/" in conv or "\\" in conv:
            continue
        try:
            rnd = int(b.get("round"))
        except (TypeError, ValueError):
            continue
        if (conv, rnd) in seen:
            continue
        row = next((r for r in read_jsonl(wux / conv)
                    if isinstance(r.get("user_text"), str)
                    and int(r.get("round") or -1) == rnd), None)
        if row is None:
            continue
        seen.add((conv, rnd))
        out.append({
            "round": rnd,
            "user_text": str(row.get("user_text") or ""),
            "summary": str(row.get("summary") or ""),
            "ts": float(row.get("ts") or 0),
            "artifacts": [str(a) for a in (row.get("artifacts") or [])],
        })
    return out


def trajectory(ws_dir: pathlib.Path, session: str = "") -> dict:
    """按轮轨迹（全工作区；孤儿 provenance 行归入 session='' 的末尾组）。"""
    wux = pathlib.Path(ws_dir) / ".wuxing"
    if session:
        name = session if session.endswith(".jsonl") else f"{session}.jsonl"
        names = [name]
    else:
        names = sorted(p.name for p in wux.glob("*.jsonl")
                       if p.name not in ("provenance.jsonl", "trace.jsonl",
                                         "unit-bindings.jsonl",
                                         "context-edits.jsonl"))
    rounds: list[dict] = []
    matched: set[tuple] = set()
    for name in names:
        for r in session_rounds(ws_dir, name)["rounds"]:
            r["session"] = name
            rounds.append(r)
            for f in r["fragments"]:
                matched.add((f["unit_id"], f["ts"]))
    # 孤儿碎片（未归属任何会话轮——如 CLI 直跑）按 task_hash 归组置末尾（session=''）
    prov = read_jsonl(wux / "provenance.jsonl")
    trace = read_jsonl(wux / "trace.jsonl")
    orphans = [p for p in prov
               if (str(p.get("unit_id") or ""), float(p.get("ts") or 0)) not in matched]
    if orphans:
        sess_dir = wux / "sessions"
        by_hash: dict[str, list[dict]] = {}
        for p in orphans:
            by_hash.setdefault(str(p.get("task_hash") or ""), []).append(p)
        for rows in by_hash.values():
            ts_all = [float(p.get("ts") or 0) for p in rows]
            info = _trace_for(rows, trace, min(ts_all) - 3600.0, max(ts_all) + 1.0)
            frags = [_frag(p, info.get(str(p.get("unit_id") or ""), {}), sess_dir, 0)
                     for p in rows]
            rounds.append({
                "round": 0, "user_text": "", "summary": "", "ts": max(ts_all),
                "artifacts": [], "parallel": any(f["parallel"] for f in frags),
                "session": "", "fragments": frags,
            })
    return {"rounds": rounds, "sessions": names}
