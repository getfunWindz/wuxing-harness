"""技能收益台账（C2 · 第二轮计划 §2；评估报告 P1）。

目的：技能自进化（默认开）的收益可量化审计——触发/复用/闲置机械可算。
- 事件侧车：``<skills_dir>/../state/<name>/usage.jsonl``（append-only；
  旧路径 ``<skills_dir>/.usage.jsonl`` 兼容读）：
    {"ts": ..., "event": "loaded"|"evolved", "skill": name, ...}
- 报表：``ledger_report``（总量/每技能 loads/last_ts/created/状态）；
- 淘汰：``unused_candidates``（长期零复用——**仅建议**）；归档为显式动作
  ``archive_skill``（移动到 ``../state/<name>/archive/``，不删除；旧 ``_archived/`` 兼容读）。

纪律：台账是观测不是生命线——写入失败静默（DEBUG 日志）、读取容忍损坏行。
"""
import json
import logging
import pathlib
import time

logger = logging.getLogger(__name__)

LEDGER_FILE = "usage.jsonl"
LEGACY_LEDGER_FILE = ".usage.jsonl"
ARCHIVE_DIR = "archive"
LEGACY_ARCHIVE_DIR = "_archived"


def state_dir(skills_dir) -> pathlib.Path:
    """P3：技能 sidecar 状态目录 = ``<skills_dir>/../state/<name>``。"""
    root = pathlib.Path(skills_dir)
    return root.parent / "state" / root.name


def ledger_path(skills_dir) -> pathlib.Path:
    return state_dir(skills_dir) / LEDGER_FILE


def legacy_ledger_path(skills_dir) -> pathlib.Path:
    return pathlib.Path(skills_dir) / LEGACY_LEDGER_FILE


def archive_dir(skills_dir) -> pathlib.Path:
    return state_dir(skills_dir) / ARCHIVE_DIR


def legacy_archive_dir(skills_dir) -> pathlib.Path:
    return pathlib.Path(skills_dir) / LEGACY_ARCHIVE_DIR


def archived_path(skills_dir, name: str) -> pathlib.Path | None:
    """归档目录查找（新 state 优先，旧 `_archived/` 兼容）。"""
    for root in (archive_dir(skills_dir), legacy_archive_dir(skills_dir)):
        p = root / str(name)
        if p.is_dir():
            return p
    return None


def record_event(skills_dir, event: str, skill: str, *, ts=None,
                 source: str = "") -> None:
    """追加一条台账事件（失败静默——观测不阻断）。"""
    if not skills_dir or not skill:
        return
    try:
        p = ledger_path(skills_dir)
        p.parent.mkdir(parents=True, exist_ok=True)
        row = {"ts": round(float(ts if ts is not None else time.time()), 3),
               "event": str(event), "skill": str(skill)}
        if source:
            row["source"] = str(source)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.debug("技能台账写入失败（不阻断）：%s", exc)


def read_events(skills_dir) -> list:
    """读取全部事件（损坏行跳过——韧性惯例；新路径优先，旧路径兼容）。"""
    p = ledger_path(skills_dir)
    if not p.exists():
        p = legacy_ledger_path(skills_dir)
    if not p.exists():
        return []
    rows = []
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    except OSError as exc:
        logger.debug("技能台账读取失败（不阻断）：%s", exc)
        return []
    return rows


def list_skills(skills_dir) -> list:
    """技能目录清单（含 SKILL.md；排除旧 `_archived`/隐藏目录）。"""
    root = pathlib.Path(skills_dir)
    if not root.is_dir():
        return []
    out = []
    for p in sorted(root.iterdir()):
        if not p.is_dir() or p.name.startswith((".", "_")):
            continue
        skill_md = p / "SKILL.md"
        if not skill_md.exists():
            continue
        try:
            created = skill_md.stat().st_mtime
        except OSError:
            created = None
        out.append({"name": p.name, "created_ts": created})
    return out


def ledger_report(skills_dir, *, now=None) -> dict:
    """机械报表：总量 + 每技能复用（loads/last_used/created/never_used）。"""
    now = float(now if now is not None else time.time())
    events = read_events(skills_dir)
    loads: dict = {}
    evolved = 0
    for e in events:
        name = str(e.get("skill") or "")
        ev = str(e.get("event") or "")
        if ev == "loaded" and name:
            row = loads.setdefault(name, {"loads": 0, "last_ts": None})
            row["loads"] += 1
            ts = e.get("ts")
            if isinstance(ts, (int, float)) \
                    and (row["last_ts"] is None or ts > row["last_ts"]):
                row["last_ts"] = float(ts)
        elif ev == "evolved":
            evolved += 1
    rows = []
    for s in list_skills(skills_dir):
        stats = loads.get(s["name"], {"loads": 0, "last_ts": None})
        rows.append({"name": s["name"], "loads": stats["loads"],
                     "last_used_ts": stats["last_ts"],
                     "created_ts": s["created_ts"],
                     "never_used": stats["loads"] == 0})
    return {"skills_total": len(rows), "evolved_events": evolved,
            "loads_total": sum(r["loads"] for r in rows),
            "skills": rows, "now": now}


def unused_candidates(skills_dir, *, days: int = 30, now=None) -> list:
    """长期零复用技能（新技能有观察期；仅建议——归档显式调用）。"""
    now = float(now if now is not None else time.time())
    horizon = max(0, int(days)) * 86400.0
    out = []
    for r in ledger_report(skills_dir, now=now)["skills"]:
        created = r["created_ts"]
        if created is None or (now - created) < horizon:
            continue  # 观察期内的新技能不判
        last = r["last_used_ts"]
        if last is None or (now - last) >= horizon:
            out.append(r["name"])
    return out


def archive_skill(skills_dir, name: str) -> dict:
    """显式归档（淘汰动作——人工/报告确认后调用；移动不删除）。

    韧性（2026-10-03 全量跑实证）：Windows 目录 rename 可能因瞬时占用
    （AV/索引器扫描新建 SKILL.md）报 WinError 5——有界重试后仍失败才报错。
    """
    root = pathlib.Path(skills_dir)
    src = root / str(name)
    if not src.is_dir():
        return {"archived": False, "reason": "not-found"}
    dest_dir = archive_dir(root)
    dest = dest_dir / str(name)
    if dest.exists():
        return {"archived": False, "reason": "exists"}
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        last_exc: OSError | None = None
        for attempt in range(3):
            try:
                src.rename(dest)
                last_exc = None
                break
            except OSError as exc:
                last_exc = exc
                if attempt < 2:
                    time.sleep(0.05 * (attempt + 1))
        if last_exc is not None:
            raise last_exc
    except OSError as exc:
        logger.debug("技能归档失败（不阻断）：%s", exc)
        return {"archived": False, "reason": f"error: {exc}"}
    return {"archived": True, "path": str(dest)}
