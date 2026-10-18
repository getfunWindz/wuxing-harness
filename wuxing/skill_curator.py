"""技能生命周期 curator（E2-1 · item 11；Hermes 对齐：确定性转换）。

设计权威：`docs/WUXING_技能专项设计_2026-10-03.md` §4。
- 状态派生（不落盘）：archived（`_archived/`）→ pinned（侧车）→ stale（空闲
  ≥14 天）→ active；最近活动 = max(最近 loaded, 创建时间)；
- 转换确定性无 LLM：stale 仅标记（报告）；archive 移动进 `_archived/`
  （**绝不删除**；`restore_skill` 可恢复；目标已存在则拒绝）；
- 零使用宽限：loads==0 时归档阈值 = ARCHIVE_DAYS + ZERO_USE_GRACE_DAYS
  （"零使用是证据缺失，不是可弃证明"）；
- pinned 豁免全部转换；内置层不在作用域（curator 只针对调用方给定的技能目录）。
"""
import pathlib
import re
import time

from wuxing import skill_ledger
from wuxing.skill_state import is_pinned
from wuxing.skills import _parse_frontmatter

STALE_DAYS = 14
ARCHIVE_DAYS = 30
ZERO_USE_GRACE_DAYS = 14
_ARCHIVE_DIR = "_archived"


def _activity(row: dict) -> float | None:
    """最近活动时间 = max(最近使用, 创建)；无时间戳 → None。"""
    vals = [v for v in (row.get("last_used_ts"), row.get("created_ts"))
            if isinstance(v, (int, float))]
    return max(vals) if vals else None


def _is_pinned_now(name: str, pinned) -> bool:
    if pinned is not None:
        return str(name) in pinned
    return is_pinned(name)


def skill_status(skills_dir, name, *, now=None, pinned=None,
                 stale_days: int = STALE_DAYS) -> str:
    """派生状态：archived / pinned / stale / active（不落盘）。"""
    name = str(name)
    root = pathlib.Path(skills_dir)
    if (root / _ARCHIVE_DIR / name).is_dir():
        return "archived"
    if _is_pinned_now(name, pinned):
        return "pinned"
    nowf = float(now if now is not None else time.time())
    row = next((r for r in skill_ledger.ledger_report(skills_dir,
                                                      now=nowf)["skills"]
                if r["name"] == name), None)
    if row is None:
        return "active"
    last = _activity(row)
    if last is None:
        return "active"
    if (nowf - last) >= float(stale_days) * 86400.0:
        return "stale"
    return "active"


def transitions_due(skills_dir, *, now=None, pinned=None,
                    stale_days: int = STALE_DAYS,
                    archive_days: int = ARCHIVE_DAYS,
                    grace_days: int = ZERO_USE_GRACE_DAYS) -> dict:
    """确定性转换建议（不落盘）：stale（报告）/ archive（动作候选）。"""
    nowf = float(now if now is not None else time.time())
    stale, archive = [], []
    for row in skill_ledger.ledger_report(skills_dir, now=nowf)["skills"]:
        name = str(row["name"])
        if _is_pinned_now(name, pinned):
            continue
        last = _activity(row)
        if last is None:
            continue
        idle_days = (nowf - last) / 86400.0
        if idle_days >= float(stale_days):
            stale.append(name)
        limit = float(archive_days) + \
            (float(grace_days) if row["loads"] == 0 else 0.0)
        if idle_days >= limit:
            archive.append(name)
    return {"stale": stale, "archive": archive, "now": nowf}


def apply_transitions(skills_dir, *, now=None, pinned=None,
                      stale_days: int = STALE_DAYS,
                      archive_days: int = ARCHIVE_DAYS,
                      grace_days: int = ZERO_USE_GRACE_DAYS) -> dict:
    """执行归档（移动不删除）；stale 仅报告。

    返回 ``{"stale": [...], "archived": [...], "failed": [...], "now": ts}``。
    """
    due = transitions_due(skills_dir, now=now, pinned=pinned,
                          stale_days=stale_days, archive_days=archive_days,
                          grace_days=grace_days)
    archived, failed = [], []
    for name in due["archive"]:
        rec = skill_ledger.archive_skill(skills_dir, name)
        (archived if rec.get("archived") else failed).append(name)
    return {"stale": due["stale"], "archived": archived, "failed": failed,
            "now": due["now"]}


def restore_skill(skills_dir, name) -> dict:
    """从 `_archived/` 恢复（可恢复语义——归档非删除；目标已存在拒绝）。

    韧性：同 archive（Windows 目录 rename 瞬时占用 → 有界重试）。
    """
    root = pathlib.Path(skills_dir)
    src = root / _ARCHIVE_DIR / str(name)
    dest = root / str(name)
    if not src.is_dir():
        return {"restored": False, "reason": "not-found"}
    if dest.exists():
        return {"restored": False, "reason": "exists"}
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
        return {"restored": False, "reason": f"error: {last_exc}"}
    return {"restored": True, "path": str(dest)}


# ---- 近义检测（2026-10-15 增补：curator 近义报告 + 自沉淀前查重）----
# 口径 = 《WUXING_技能去重报告_2026-10-06》§方法：名称词元 Jaccard ≥0.4
# 或 正文去空白后字符二元组 Jaccard ≥0.28（人工复核兜底；只报告不自动合并）。
NEAR_NAME_J = 0.4
NEAR_BODY_J = 0.28
_FM_BLOCK_RE = re.compile(r"^---\s*\n(.*?)\n---\s*(\n|$)", re.DOTALL)


def _split_skill_md(text: str) -> tuple:
    """SKILL.md → (frontmatter, 正文)；无有效 frontmatter → (None, text)。"""
    fm = _parse_frontmatter(text)
    if fm is None:
        return None, text
    m = _FM_BLOCK_RE.match(text)
    return fm, (text[m.end():] if m else text)


def load_skills(skills_dir) -> list:
    """现役技能卡（name/description/body/created_ts）；破损跳过（注册表口径）。"""
    root = pathlib.Path(skills_dir)
    out = []
    for s in skill_ledger.list_skills(root):
        name = str(s["name"])
        try:
            text = (root / name / "SKILL.md").read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue  # 读失败 → 跳过（与技能注册表破损跳过一致）
        fm, body = _split_skill_md(text)
        if fm is None:
            continue
        out.append({"name": name,
                    "description": str(fm.get("description", "")).strip(),
                    "body": body,
                    "created_ts": s.get("created_ts")})
    return out


def name_tokens(name) -> set:
    """名称词元（kebab 分词，小写）。"""
    return {t for t in str(name or "").lower().split("-") if t}


def bigrams(text) -> set:
    """字符二元组（去全部空白；中文可用；空文本 → 空集）。"""
    s = re.sub(r"\s+", "", str(text or ""))
    if len(s) < 2:
        return {s} if s else set()
    return {s[i:i + 2] for i in range(len(s) - 1)}


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def pair_similarity(name_a, body_a, name_b, body_b, *,
                    name_threshold: float = NEAR_NAME_J,
                    body_threshold: float = NEAR_BODY_J) -> dict:
    """一对技能的相似度（name 词元 J / 正文 bigram J）与命中判定。"""
    nj = jaccard(name_tokens(name_a), name_tokens(name_b))
    bj = jaccard(bigrams(body_a), bigrams(body_b))
    matched_by = []
    if nj >= float(name_threshold):
        matched_by.append("name")
    if bj >= float(body_threshold):
        matched_by.append("body")
    return {"name_j": round(nj, 4), "body_j": round(bj, 4),
            "matched_by": matched_by, "match": bool(matched_by)}


def near_duplicate_report(skills_dir, *, name_threshold: float = NEAR_NAME_J,
                          body_threshold: float = NEAR_BODY_J,
                          now=None) -> dict:
    """近义检测报告（只读；现役技能；union-find 成簇）——只报告不修改。"""
    nowf = float(now if now is not None else time.time())
    skills = load_skills(skills_dir)
    parent = {s["name"]: s["name"] for s in skills}

    def _find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    pairs = []
    for i in range(len(skills)):
        for j in range(i + 1, len(skills)):
            a, b = skills[i], skills[j]
            sim = pair_similarity(a["name"], a["body"], b["name"], b["body"],
                                  name_threshold=name_threshold,
                                  body_threshold=body_threshold)
            if not sim["match"]:
                continue
            pairs.append({"a": a["name"], "b": b["name"],
                          "name_j": sim["name_j"], "body_j": sim["body_j"],
                          "matched_by": sim["matched_by"]})
            ra, rb = _find(a["name"]), _find(b["name"])
            if ra != rb:
                parent[rb] = ra

    groups: dict = {}
    for s in skills:
        groups.setdefault(_find(s["name"]), []).append(s)
    ledger = {r["name"]: r for r in
              skill_ledger.ledger_report(skills_dir, now=nowf)["skills"]}

    def _canonical_key(card: dict):
        row = ledger.get(card["name"], {})
        created = row.get("created_ts")
        return (-int(row.get("loads") or 0),
                created if isinstance(created, (int, float)) else float("inf"),
                card["name"])

    clusters, singletons = [], []
    for members in groups.values():
        if len(members) < 2:
            singletons.extend(str(m["name"]) for m in members)
            continue
        names = {str(m["name"]) for m in members}
        canon_card = min(members, key=_canonical_key)
        canon = str(canon_card["name"])
        in_cluster = [p for p in pairs if p["a"] in names and p["b"] in names]
        clusters.append({
            "members": sorted(names),
            "max_name_j": max(p["name_j"] for p in in_cluster),
            "max_body_j": max(p["body_j"] for p in in_cluster),
            "canonical": canon,
            "canonical_description": canon_card["description"],
            "canonical_loads": int((ledger.get(canon) or {}).get("loads") or 0),
        })
    clusters.sort(key=lambda c: c["members"][0])
    singletons.sort()
    pairs.sort(key=lambda p: (p["a"], p["b"]))
    return {"skills_total": len(skills),
            "thresholds": {"name": float(name_threshold),
                           "body": float(body_threshold)},
            "pairs": pairs, "clusters": clusters,
            "singletons": singletons, "now": nowf}


def find_near_duplicate(skills_dir, *, name, body,
                        name_threshold: float = NEAR_NAME_J,
                        body_threshold: float = NEAR_BODY_J) -> dict | None:
    """草稿 vs 现役技能：最近命中（body_j 优先，并列取 name_j）或 None。"""
    best = None
    for s in load_skills(skills_dir):
        sim = pair_similarity(name, body, s["name"], s["body"],
                              name_threshold=name_threshold,
                              body_threshold=body_threshold)
        if not sim["match"]:
            continue
        cand = {"name": s["name"], "description": s["description"],
                "name_j": sim["name_j"], "body_j": sim["body_j"]}
        if best is None or (cand["body_j"], cand["name_j"]) > \
                (best["body_j"], best["name_j"]):
            best = cand
    return best


def format_near_duplicate_report(report: dict) -> str:
    """人读摘要（CLI 用；只读展示——canonical 现状描述供人工强化）。"""
    lines = [(f"近义簇 {len(report['clusters'])} 组 · 现役技能 "
              f"{report['skills_total']} · 阈值 name≥"
              f"{report['thresholds']['name']:.2f} / body≥"
              f"{report['thresholds']['body']:.2f}")]
    for idx, c in enumerate(report["clusters"], 1):
        lines.append(f"[C{idx}] {len(c['members'])} 个 · 建议 canonical："
                     f"{c['canonical']}（loads {c['canonical_loads']}）")
        lines.append(f"      现状描述：{c.get('canonical_description') or '（无）'}"
                     "（供强化）")
        lines.append("      - " + " / ".join(c["members"]))
    singles = report.get("singletons") or []
    lines.append(f"无近义（单例）{len(singles)} 个："
                 + ("、".join(singles) if singles else "（无）"))
    return "\n".join(lines)
