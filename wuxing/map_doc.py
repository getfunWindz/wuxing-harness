"""工作区地图 WUXING.md（双模式批 3 · 设计 §5.4）。

受控结构（供解析）：
  # <项目名> · WUXING 地图
  ## 目的地 / ## 路线 / ## 决策记录（append-only）/ ## 未定 / ## 范围外
纪律：文件头注明「由 WUXING 维护」；段替换走清单归一；原子写；解析容错（缺段 → 空）。
"""
from __future__ import annotations

import hashlib
import pathlib
import re
import time

from wuxing.atomic_write import atomic_write_text
from wuxing.filelock import lock_for

MAP_FILENAME = "WUXING.md"
SECTIONS = ("目的地", "路线", "决策记录", "未定", "范围外")

# 真测观察（THEROAD E2E）：设计模型把多条目写成单行 `<br>` 分隔——
# 读/写两侧都归一为逐行，防 digest/简报单行排版。
_BR_RE = re.compile(r"<\s*br\s*/?\s*>", re.IGNORECASE)


def _split_br(text: str) -> list[str]:
    """`<br>`/`<br/>`/`<br />`（大小写不敏感）→ 逐行拆分。"""
    return [x.strip() for x in _BR_RE.split(str(text or "")) if x.strip()]


def map_path(workdir) -> pathlib.Path:
    return pathlib.Path(workdir) / MAP_FILENAME


def template(project: str = "") -> str:
    name = project or "未命名"
    return (f"# {name} · WUXING 地图\n\n"
            "> 由 WUXING 维护（本文件为工作区级地图：目的地/路线/决策记录/未定/范围外）\n\n"
            + "".join(f"## {s}\n\n" for s in SECTIONS))


def parse(text) -> dict:
    src = str(text or "")
    out = {"project": "", "destination": "", "route": [], "decisions": [],
           "fog": [], "out_of_scope": []}
    lines = src.splitlines()
    if lines and lines[0].startswith("# "):
        head = lines[0][2:].strip()
        out["project"] = head.split("·")[0].strip()
    cur = ""
    buf: list[str] = []

    def flush():
        if not cur:
            return
        body = [l.rstrip() for l in buf if l.strip()]
        if cur == "目的地":
            out["destination"] = "\n".join(body)
        elif cur == "路线":
            out["route"] = [x for line in body for x in _split_br(line)]
        elif cur == "决策记录":
            out["decisions"] = body
        elif cur == "未定":
            out["fog"] = [x for line in body for x in _split_br(line)]
        elif cur == "范围外":
            out["out_of_scope"] = [x for line in body for x in _split_br(line)]

    for line in lines[1:]:
        if line.startswith("## "):
            flush()
            cur = line[3:].strip()
            buf = []
        elif cur:
            buf.append(line)
    flush()
    return out


def read(workdir) -> dict | None:
    p = map_path(workdir)
    if not p.is_file():
        return None
    try:
        return parse(p.read_text(encoding="utf-8"))
    except OSError:
        # 地图文件缺失/不可读 → None（视为无地图，按需重建）
        return None


def _norm_lines(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        items = [str(v) for v in value]
    else:
        items = str(value).splitlines()
    out: list[str] = []
    for item in items:
        out.extend(_split_br(item))  # <br> 分隔 → 逐行（真测观察归一）
    return out


def write_sections(workdir, *, project="", destination=None, route=None,
                   decisions=None, fog=None, out_of_scope=None) -> str:
    """段更新写（目的地/路线/未定/范围外 替换；决策记录 append）+ 原子写。

    G8-M2：读改写整体入路径级锁——多实例并发写地图不丢段。
    """
    p = map_path(workdir)
    with lock_for(p):
        cur = parse(p.read_text(encoding="utf-8")) if p.is_file() else parse("")
        if project:
            cur["project"] = project
        if destination is not None:
            cur["destination"] = "\n".join(_norm_lines(destination))
        if route is not None:
            cur["route"] = _norm_lines(route)
        if decisions is not None:
            cur["decisions"] = cur["decisions"] + _norm_lines(decisions)
        if fog is not None:
            cur["fog"] = _norm_lines(fog)
        if out_of_scope is not None:
            cur["out_of_scope"] = _norm_lines(out_of_scope)
        name = cur["project"] or "未命名"
        body = [f"# {name} · WUXING 地图", "",
                "> 由 WUXING 维护（本文件为工作区级地图：目的地/路线/决策记录/未定/范围外）", ""]

        def sec(title: str, lines: list[str]):
            body.append(f"## {title}")
            body.append("")
            body.extend(lines)
            body.append("")

        sec("目的地", [cur["destination"]] if cur["destination"] else [])
        sec("路线", cur["route"])
        sec("决策记录", cur["decisions"])
        sec("未定", cur["fog"])
        sec("范围外", cur["out_of_scope"])
        text = "\n".join(body).rstrip() + "\n"
        atomic_write_text(p, text)
        return text


def file_hash(path) -> str:
    try:
        return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()
    except OSError:
        # 读不到文件 → 空哈希（地图指纹缺省）
        return ""


def is_usable(workdir) -> bool:
    d = read(workdir)
    if not d:
        return False
    return bool(d.get("destination") or d.get("route"))


def digest(workdir, max_chars: int = 600) -> str:
    d = read(workdir)
    if not d:
        return ""
    parts = [f"# 工作区地图：{d.get('project') or '未命名'}"]
    if d.get("destination"):
        parts.append("目的地：" + d["destination"])
    if d.get("route"):
        parts.append("路线：\n" + "\n".join(d["route"][:12]))
    if d.get("fog"):
        parts.append("未定：" + "；".join(d["fog"][:6]))
    text = "\n".join(parts)
    return text[:max_chars]


# ---- 结构化决策（二期批 2）：解析 / DAG 派生 / 追加 ----

_DEC_ID_RE = re.compile(r"^\[(?P<id>D-\d+)\]\s*(?P<rest>.*)$")
_DEC_DATE_RE = re.compile(r"^(?P<date>\d{4}-\d{2}-\d{2})\s*(?P<rest>.*)$")
_DEC_FIELDS = (("理由：", "why"), ("上游：", "upstream"),
               ("取代：", "supersedes"), ("来源：", "source"))


def parse_decisions(lines) -> list[dict]:
    """决策记录段 → 结构化条目（容错：旧自由文本行保留为 text——id=""）。

    结构化行（append_decision 产出口径，`｜` 分隔）：
      - [D-1] 2026-09-25 决策：文本｜理由：…｜上游：D-x｜取代：D-y｜来源：Q-n
    """
    out: list[dict] = []
    for raw in lines or []:
        s = str(raw).strip()
        if s.startswith("-"):
            s = s[1:].strip()
        if not s:
            continue
        m = _DEC_ID_RE.match(s)
        if m is None:
            out.append({"id": "", "date": "", "text": s, "why": "",
                        "upstream": [], "supersedes": [], "source": ""})
            continue
        did, rest = m.group("id"), m.group("rest").strip()
        segs = [x.strip() for x in rest.split("｜")]
        head = segs[0] if segs else ""
        date = ""
        dm = _DEC_DATE_RE.match(head)
        if dm:
            date, head = dm.group("date"), dm.group("rest").strip()
        if head.startswith("决策："):
            head = head[len("决策："):].strip()
        item = {"id": did, "date": date, "text": head, "why": "",
                "upstream": [], "supersedes": [], "source": ""}
        for seg in segs[1:]:
            for key, dest in _DEC_FIELDS:
                if not seg.startswith(key):
                    continue
                val = seg[len(key):].strip()
                if dest in ("upstream", "supersedes"):
                    item[dest] = [x for x in re.split(r"[，,、\s]+", val)
                                  if re.fullmatch(r"D-\d+", x)]
                else:
                    item[dest] = "" if val in ("—", "-") else val
        out.append(item)
    return out


def heads(decisions) -> list[str]:
    """现行分支末梢：未被取代且没有未取代子节点的决策 id（文件序）。"""
    superseded = {s for d in decisions for s in (d.get("supersedes") or [])}
    alive = {d["id"] for d in decisions if d.get("id") and d["id"] not in superseded}
    has_child: set[str] = set()
    for d in decisions:
        if not d.get("id") or d["id"] in superseded:
            continue
        for up in d.get("upstream") or []:
            has_child.add(up)
    order = [d["id"] for d in decisions if d.get("id")]
    return [i for i in order if i in alive and i not in has_child]


def branch(decisions, head: str) -> list[str]:
    """从 head 沿上游回溯的分支 id 链（防环：已访问即停）。"""
    by_id = {d["id"]: d for d in decisions if d.get("id")}
    out: list[str] = []
    cur = str(head or "")
    while cur and cur in by_id and cur not in out:
        out.append(cur)
        ups = by_id[cur].get("upstream") or []
        cur = ups[0] if ups else ""
    return out


def append_decision(workdir, *, text, why="", upstream="", supersedes="",
                    source="", date="") -> dict:
    """追加结构化决策行（D-n 顺序分配；决策记录 append-only）。

    G8-M2：分配+写入整体入路径级锁——并发 append 不撞号。
    """
    with lock_for(map_path(workdir)):
        data = read(workdir) or parse("")
        used = [int(d["id"][2:]) for d in parse_decisions(data.get("decisions") or [])
                if d.get("id")]
        did = f"D-{max(used) + 1 if used else 1}"
        day = str(date or time.strftime("%Y-%m-%d"))
        up = str(upstream or "").strip() or "—"
        sup = str(supersedes or "").strip() or "—"
        line = (f"- [{did}] {day} 决策：{str(text or '').strip()}"
                f"｜理由：{str(why or '').strip() or '—'}"
                f"｜上游：{up}｜取代：{sup}"
                f"｜来源：{str(source or '').strip() or '—'}")
        write_sections(workdir, decisions=[line])
        return {"id": did, "date": day, "text": str(text or "").strip(),
                "why": str(why or "").strip(),
                "upstream": [] if up == "—" else [up],
                "supersedes": [] if sup == "—" else [sup],
                "source": str(source or "").strip()}
