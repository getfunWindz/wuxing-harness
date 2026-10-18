"""WUXING spec（二期批 3 · 设计 §7）：临时规格——票据全关后的收敛产物。

目录：`<workdir>/.wuxing/specs/<slug>.md`（slug 默认 spec-<YYYYMMDD-HHMM>）。
受控七段（供实施票据切分解析）：
  Problem Statement / Solution / User Stories / Implementation Decisions /
  Testing Decisions / Out of Scope / Further Notes
纪律：原子写；解析容错（缺段→空）；「不写文件路径与代码片段」由设计提示词
纪律承载（机制不硬校验——软编排）。
"""
from __future__ import annotations

import hashlib
import pathlib
import time

from wuxing.atomic_write import atomic_write_text

SPEC_SECTIONS = (
    ("problem", "Problem Statement"),
    ("solution", "Solution"),
    ("stories", "User Stories"),
    ("decisions", "Implementation Decisions"),
    ("testing", "Testing Decisions"),
    ("out_of_scope", "Out of Scope"),
    ("notes", "Further Notes"),
)
_HEADER = "WUXING spec"


def specs_dir(workdir) -> pathlib.Path:
    return pathlib.Path(workdir) / ".wuxing" / "specs"


def spec_path(workdir, slug: str) -> pathlib.Path:
    name = str(slug or "").strip()
    if name == "" or "/" in name or "\\" in name or name in (".", ".."):
        raise ValueError(f"非法 spec slug：{slug!r}")
    if not name.endswith(".md"):
        name += ".md"
    return specs_dir(workdir) / name


def default_slug() -> str:
    return "spec-" + time.strftime("%Y%m%d-%H%M")


def render(title: str, sections: dict) -> str:
    name = str(title or "").strip() or "未命名"
    body = [f"# {name} · {_HEADER}", "",
            "> 由 WUXING 维护（临时规格——验收后可按需清理）", ""]
    for key, heading in SPEC_SECTIONS:
        body.append(f"## {heading}")
        body.append("")
        value = sections.get(key) or ""
        if isinstance(value, (list, tuple)):
            value = "\n".join(f"- {str(v).strip()}"
                              for v in value if str(v).strip())
        if str(value).strip():
            body.extend(str(value).splitlines())
        body.append("")
    return "\n".join(body).rstrip() + "\n"


def write(workdir, *, title, sections, slug="") -> dict:
    """原子写 spec；返回 {slug, path, hash}（slug 缺省 spec-YYYYMMDD-HHMM）。"""
    final = str(slug or "").strip() or default_slug()
    path = spec_path(workdir, final)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = render(title, sections)
    atomic_write_text(path, text)
    return {"slug": path.stem, "path": str(path),
            "hash": hashlib.sha256(text.encode("utf-8")).hexdigest()}


def parse(text) -> dict:
    """受控七段解析（容错：缺段→空；未知段忽略；标题取 `# ` 首行）。"""
    out = {"title": "", "sections": {k: "" for k, _ in SPEC_SECTIONS}}
    lines = str(text or "").splitlines()
    if lines and lines[0].startswith("# "):
        out["title"] = lines[0][2:].strip().split("·")[0].strip()
    lookup = {h: k for k, h in SPEC_SECTIONS}
    cur: str | None = None
    buf: list[str] = []

    def flush():
        if cur is not None:
            out["sections"][cur] = "\n".join(
                line for line in buf if line.strip()).strip()

    start = 1 if (lines and lines[0].startswith("# ")) else 0
    for line in lines[start:]:
        if line.startswith("## "):
            flush()
            cur = lookup.get(line[3:].strip())
            buf = []
        elif cur is not None:
            buf.append(line.rstrip())
    flush()
    return out


def read(workdir, slug: str) -> str:
    """读取 spec 文本（缺失/非法 slug/IO 失败 → 空串——读侧容错）。"""
    try:
        p = spec_path(workdir, slug)
    except ValueError:
        # slug 非法 → 空串（读侧容错：不抛错）
        return ""
    if not p.is_file():
        return ""
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        # 读不到文件 → 空串（读侧容错）
        return ""


def latest(workdir):
    """最新 spec（按 mtime；无 → None）→ (slug, path)。"""
    d = specs_dir(workdir)
    if not d.is_dir():
        return None
    files = [p for p in d.glob("*.md") if p.is_file()]
    if not files:
        return None
    p = max(files, key=lambda x: x.stat().st_mtime)
    return p.stem, p
