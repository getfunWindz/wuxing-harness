"""决策历史（#2 backlog T-5）：用户面「我批准过什么」——trace 审计对还原。

- 数据源：workspace `.wuxing/trace.jsonl`（只读，不改写）；
- 三面：confirm_asked↔confirm_decided（unit_id）/ question_asked↔question_answered
  （question_id）/ browser_access_decided（单条）；
- 未决（asked 无 decided）保留 `status="pending"`（不假装已决）；
- fail-closed：缺文件=空；损坏行跳过。
"""
import json
import pathlib

_CAP = 2000   # 读取上限（性能护栏；超出取最近 N 行）


def load_decisions(ws_root, limit: int = 200) -> dict:
    """trace → 决策条目（倒序；未决保留；{entries, problems}）。"""
    path = pathlib.Path(ws_root) / ".wuxing" / "trace.jsonl"
    rows = []
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue        # 损坏行跳过（韧性惯例）
        except OSError as exc:
            return {"entries": [], "problems": [f"{path} 读取失败：{exc}"]}
    rows = rows[-_CAP:]
    wait_c, wait_q, entries = {}, {}, []

    def _confirm_entry(row, decided):
        status = "pending"
        if decided is not None:
            status = ("approved" if decided.get("decision") == "approve"
                      else "rejected")
        return {"kind": "confirm", "ts": row.get("ts", 0.0),
                "asked_ts": row.get("ts", 0.0),
                "unit_id": str(row.get("unit_id", "")),
                "domain": str(row.get("domain", "")),
                "object": str(row.get("unit_id", "")),
                "status": status,
                "reason": str((decided or row).get("reason", "") or ""),
                "source": str(row.get("surface", "") or "")}

    for row in rows:
        ev = str(row.get("event") or "")
        if ev == "confirm_asked":
            wait_c[str(row.get("unit_id", ""))] = row
        elif ev == "confirm_decided":
            uid = str(row.get("unit_id", ""))
            asked = wait_c.pop(uid, {})
            e = _confirm_entry(asked or row, row)
            e["ts"] = row.get("ts", e["ts"])
            entries.append(e)
        elif ev == "question_asked":
            wait_q[str(row.get("question_id", ""))] = row
        elif ev == "question_answered":
            qid = str(row.get("question_id", ""))
            asked = wait_q.pop(qid, {})
            entries.append({
                "kind": "question", "ts": row.get("ts", 0.0),
                "asked_ts": asked.get("ts", 0.0),
                "unit_id": str(row.get("unit_id", "")),
                "domain": str(asked.get("domain", "")),
                "object": qid,
                "status": "answered",
                "reason": str(row.get("answer", "") or "")[:300],
                "source": str(row.get("source", "") or "")})
        elif ev == "browser_access_decided":
            entries.append({
                "kind": "browser_access", "ts": row.get("ts", 0.0),
                "asked_ts": row.get("ts", 0.0),
                "unit_id": "", "domain": "",
                "object": str(row.get("address", "")),
                "status": ("approved" if row.get("approved")
                           else "rejected"),
                "reason": str(row.get("note", "") or ""),
                "source": str(row.get("kind", "") or "")})
    for uid, row in wait_c.items():               # 未决确认
        entries.append(_confirm_entry(row, None))
    for qid, row in wait_q.items():               # 未决提问
        entries.append({
            "kind": "question", "ts": row.get("ts", 0.0),
            "asked_ts": row.get("ts", 0.0),
            "unit_id": str(row.get("unit_id", "")),
            "domain": str(row.get("domain", "")),
            "object": qid, "status": "pending", "reason": "",
            "source": str(row.get("kind", "") or "")})
    entries.sort(key=lambda e: float(e.get("ts") or 0.0), reverse=True)
    return {"entries": entries[:max(1, int(limit))], "problems": []}
