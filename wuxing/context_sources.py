"""上下文来源侧车（A 期 A1）：会话级持久开关 + 预算覆盖 + 指纹工具。

文件：`<workdir>/.wuxing/context-sources.json`（原子写；缺失/损坏 → 全默认）。
默认全开（旧数据/无文件 → 装配字节不变——缓存纪律）。
壳写引擎读（与 `context-edits.jsonl` 同模式）；`resolve` 供 runner/orchestrator
装配使用；`content_fp` 与壳侧同源（跨模块冻结测试守卫漂移）。
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import time

_FILENAME = "context-sources.json"
_BOOL_KEYS = ("history", "digest", "skills", "prefix")
_SCOPES = ("conversations", "units")


def sources_path(workdir) -> pathlib.Path:
    return pathlib.Path(workdir) / ".wuxing" / _FILENAME


def content_fp(text) -> str:
    """内容指纹（sha1[:12]；空串 → 空——三键防护用，不 strip）。"""
    s = str(text or "")
    if s == "":
        return ""
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:12]


def load(workdir) -> dict:
    p = sources_path(workdir)
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _scoped(data: dict, scope: str, key: str) -> dict:
    if not key:
        return {}
    raw = data.get(scope)
    if not isinstance(raw, dict):
        return {}
    item = raw.get(str(key))
    return item if isinstance(item, dict) else {}


def _merge(out: dict, values: dict) -> None:
    for k in _BOOL_KEYS:
        if isinstance(values.get(k), bool):
            out[k] = values[k]
    b = values.get("budget_tokens")
    if isinstance(b, (int, float)) and not isinstance(b, bool):
        out["budget_tokens"] = max(0, int(b))


def resolve(workdir, *, conversation: str = "", unit: str = "",
            default_budget: int = 0) -> dict:
    """有效来源（默认全开）+ 预算（unit > conversation > default）。"""
    data = load(workdir)
    out = {k: True for k in _BOOL_KEYS}
    out["budget_tokens"] = max(0, int(default_budget or 0))
    _merge(out, _scoped(data, "conversations", conversation))
    _merge(out, _scoped(data, "units", unit))
    return out


def load_unit_edits(workdir, unit: str) -> list:
    """unit 域投影层编辑（`context-edits.jsonl` 中 `kind=="unit"` 记录）。

    append-only；同 (file, index) 最新生效；按 (file,index) 升序返回（应用确定性）。
    """
    uid = str(unit or "")
    if uid == "":
        return []
    path = pathlib.Path(workdir) / ".wuxing" / "context-edits.jsonl"
    if not path.is_file():
        return []
    latest: dict = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except (ValueError, json.JSONDecodeError):
            continue
        if str(row.get("kind") or "") != "unit":
            continue
        if str(row.get("unit") or "") != uid:
            continue
        try:
            idx = int(row.get("index"))
        except (TypeError, ValueError):
            continue
        op = str(row.get("op") or "")
        key = (str(row.get("file") or ""), idx)
        if op == "restore":
            # G3：回到原文（append-only 审计保留；同目标后续仍可再叠加）
            latest.pop(key, None)
            continue
        if op not in ("omit", "replace"):
            continue
        latest[key] = {
            "file": str(row.get("file") or ""),
            "index": idx,
            "fp_in": str(row.get("fp_in") or ""),
            "fp_out": str(row.get("fp_out") or ""),
            "op": op,
            "content": str(row.get("content") or ""),
        }
    return [latest[k] for k in sorted(latest, key=lambda x: (x[0], x[1]))]


def save(workdir, scope: str, key: str, values: dict) -> dict:
    """读-改-写（部分键更新；非法类型忽略；原子替换——失败静默）。"""
    if scope not in _SCOPES:
        raise ValueError(f"未知作用域：{scope}")
    k = str(key or "").strip()
    if k == "":
        raise ValueError("作用域键不能为空")
    p = sources_path(workdir)
    data = load(workdir)
    data.setdefault("version", 1)
    bucket = data.get(scope)
    if not isinstance(bucket, dict):
        bucket = {}
        data[scope] = bucket
    item = bucket.get(k)
    if not isinstance(item, dict):
        item = {}
        bucket[k] = item
    for name in _BOOL_KEYS:
        if isinstance(values.get(name), bool):
            item[name] = values[name]
    b = values.get("budget_tokens")
    if isinstance(b, (int, float)) and not isinstance(b, bool):
        item["budget_tokens"] = max(0, int(b))
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return resolve(workdir,
                       conversation=(k if scope == "conversations" else ""),
                       unit=(k if scope == "units" else ""))
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    for attempt in range(3):
        try:
            tmp = p.with_name(p.name + ".tmp")
            tmp.write_text(payload, encoding="utf-8")
            tmp.replace(p)          # Windows 瞬态占用重试（项目惯例）
            break
        except OSError:
            time.sleep(0.02 * (attempt + 1))
    return resolve(workdir,
                   conversation=(k if scope == "conversations" else ""),
                   unit=(k if scope == "units" else ""))
