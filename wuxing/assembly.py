"""G5 装配代际与失败可视（设计 2026-09-26）。

装配 = 引擎构造时的显式组件面（配置/工具/扩展/技能/MCP/版本）：
- ``assembly_id``：装配面内容指纹（sha256 前 12 位）——同装配同 id，任一变化 id 变；
- ``assembly.json``（workdir 沙盒）：当前代 + 上一代 id（变更可追踪）；
- ``degraded``：可降级失败明细（扩展 broken / MCP 未装载）——报告/trace/壳三面可见。

fatal（配置非法等构造期异常）保持既有 fail-fast（不吞错不半装配），本模块不新增硬拒绝。
"""
import dataclasses
import hashlib
import json
import pathlib
import time

from wuxing.atomic_write import atomic_write_text
from wuxing.filelock import lock_for

RECORD_NAME = "assembly.json"
SCHEMA_VERSION = 1


def _sha12(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _file_sha12(path: pathlib.Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    except OSError:
        # 读不到文件 → 无法计算指纹：返 None（装配代际按缺失处理）
        return None


def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)


def _extensions_fingerprint(dirs) -> list[dict]:
    out: list[dict] = []
    for root in (dirs or ()):
        root = pathlib.Path(root)
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*.py")):
            if path.name.startswith("_"):
                continue  # __init__.py / 辅助模块不入扩展面（与加载器口径一致）
            digest = _file_sha12(path)
            if digest is not None:
                out.append({"path": path.name, "sha": digest})
    return out


def _skills_fingerprint(skills) -> list[dict]:
    if skills is None:
        return []
    try:
        index = skills.index()
    except Exception:
        return []
    out: list[dict] = []
    for name, info in sorted(index.items()):
        base = pathlib.Path(str((info or {}).get("path") or ""))
        digest = _file_sha12(base / "SKILL.md") if str(base) else None
        out.append({"name": str(name), "sha": digest})
    return out


def collect_components(cfg, *, isolated: bool, tool_names, skills,
                       extension_dirs=(), mcp_cfgs=()) -> dict:
    """装配面组件（决定指纹的内容；不含密钥值——配置内仅凭据 ref 名）。"""
    from wuxing import __version__
    return {
        "version": str(__version__),
        "isolated": bool(isolated),
        "tools": sorted(str(n) for n in (tool_names or ())),
        "config": _canonical(dataclasses.asdict(cfg)),
        "extensions": _extensions_fingerprint(extension_dirs),
        "skills": _skills_fingerprint(skills),
        "mcp": [
            {"name": str(getattr(c, "name", "")),
             "command": str(getattr(c, "command", "")),
             "args": [str(a) for a in (getattr(c, "args", None) or [])],
             "env_keys": sorted(str(k) for k in
                                (getattr(c, "env", None) or {}))}
            for c in (mcp_cfgs or ())
        ],
    }


def fingerprint(components: dict) -> str:
    """装配面 → 代际 id（内容指纹；确定性、跨机可复现——不用 mtime）。"""
    return _sha12(_canonical(components))


def _split_problem(text: str) -> tuple[str, str]:
    idx = text.find("（")
    if 0 <= idx and text.endswith("）"):
        return text[:idx], text[idx + 1:-1]
    return text, ""


def degraded_items(ext_result, *, mcp_configured=(), mcp_loaded_names=()) -> list[dict]:
    """可降级失败明细（不阻断——分类：fatal 走构造期上抛，不进此列）。"""
    out: list[dict] = []
    for problem in list(getattr(ext_result, "problems", None) or []):
        name, reason = _split_problem(str(problem))
        out.append({"component": "extensions", "name": name, "reason": reason})
    loaded = {str(n) for n in (mcp_loaded_names or ())}
    for cfg in (mcp_configured or ()):
        name = str(getattr(cfg, "name", ""))
        if name and name not in loaded:
            out.append({"component": "mcp", "name": name,
                        "reason": "未装载（连接失败或无工具）"})
    return out


def record_generation(workdir, *, id: str, components: dict,
                      degraded: list | None = None) -> dict:
    """原子写 ``<workdir>/.wuxing/assembly.json``；返回记录。

    previous_id：新旧 id 不同 → 记旧 id；相同 → 保留既有 previous_id（同代不刷）。
    写失败上抛（调用方 fail-safe + trace 注记——观测不阻断执行）。
    """
    path = pathlib.Path(workdir) / ".wuxing" / RECORD_NAME
    with lock_for(path):
        previous = None
        try:
            if path.exists():
                prev = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(prev, dict):
                    if str(prev.get("id")) != str(id):
                        previous = prev.get("id")
                    else:
                        previous = prev.get("previous_id")
        except (OSError, ValueError):
            previous = None
        record = {
            "version": SCHEMA_VERSION,
            "id": str(id),
            "computed_at": round(time.time(), 3),
            "previous_id": previous,
            "components": components,
            "degraded": list(degraded or []),
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, json.dumps(record, ensure_ascii=False, indent=2))
    return record


def format_report_note(assembly: dict, *, mode: str = "",
                       tool_count: int = 0) -> str:
    """报告尾部装配注记（id 行 + degraded 逐条原因；空装配 → ""）。"""
    if not assembly or not assembly.get("id"):
        return ""
    lines = [(f"[装配] id={assembly.get('id')} · 模式={mode or '-'}"
              f" · 工具 {int(tool_count)}")]
    for item in (assembly.get("degraded") or []):
        lines.append(f"  - [装配降级] {item.get('component')}/"
                     f"{item.get('name')}：{item.get('reason')}")
    return "\n".join(lines)
