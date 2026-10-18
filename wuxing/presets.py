"""装配预设（E2-4）：preset 组合树（extends 链 + 深合并）+ 解析 + 会话绑定。

来源（后者覆盖同名）：内置（代码：standard/lean）→ 用户级
`~/.wuxing/presets/<name>.jsonc` → 工作区 `.wuxing/presets/<name>.jsonc`。

语义：
- `extends` 继承链；环/未知 extends → ValueError；
- 合并：父 → 子逐层（子级 `tools` 覆盖；enable/disable 列表并集去重保序）；
- `resolve_for_session`：会话 sidecar > 配置默认；解析失败回退 standard（不阻断引擎）。

生效面（由 Engine 消费）：extensions{enable,disable} / tools / prompt_segments{disable} /
skills{disable}；解析结果 hash 进 G5 装配代际（assembly components.preset）。
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import time

from wuxing.atomic_write import atomic_write_text
from wuxing.config_loader import parse_jsonc
from wuxing.filelock import lock_for

_BUILTIN: dict[str, dict] = {
    "standard": {"description": "默认装配（全部默认行为）"},
    "lean": {"description": "精简装配（核心五件工具 + 无扩展/提示词段/技能）",
             "extends": "standard",
             "extensions": {"disable": ["*"]},
             "tools": ["bash", "read_file", "write_file", "write_artifact",
                       "read_dependency"],
             "prompt_segments": {"disable": ["*"]},
             "skills": {"disable": ["*"]}},
}

_SESSION_FILE = "session-presets.json"


def presets_dir(workdir, *, user: bool = False) -> pathlib.Path:
    if user:
        import os
        return pathlib.Path(os.path.expanduser("~")) / ".wuxing" / "presets"
    return pathlib.Path(workdir) / ".wuxing" / "presets"


def _normalize(raw: dict, name: str) -> dict:
    ext = raw.get("extensions") or {}
    ps = raw.get("prompt_segments") or {}
    sk = raw.get("skills") or {}
    return {
        "name": name,
        "extends": str(raw.get("extends") or "").strip(),
        "description": str(raw.get("description") or ""),
        "extensions": {
            "enable": [str(x) for x in (ext.get("enable") or [])],
            "disable": [str(x) for x in (ext.get("disable") or [])],
        },
        "tools": (None if raw.get("tools") is None
                  else [str(x) for x in (raw.get("tools") or [])]),
        "prompt_segments": {
            "disable": [str(x) for x in (ps.get("disable") or [])]},
        "skills": {"disable": [str(x) for x in (sk.get("disable") or [])]},
    }


def load_all(workdir=None) -> dict[str, dict]:
    """全部预设（内置 + 用户级 + 工作区；同名后者覆盖）。"""
    out = {name: _normalize(raw, name) for name, raw in _BUILTIN.items()}
    layers = [presets_dir(workdir, user=True)]
    if workdir is not None:
        layers.append(presets_dir(workdir))
    for d in layers:
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.jsonc")):
            try:
                raw = parse_jsonc(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue  # 破损预设跳过（可见性经 CLI/壳列表缺项体现）
            if isinstance(raw, dict):
                out[p.stem] = _normalize(raw, p.stem)
    return out


def list_presets(workdir=None) -> list[dict]:
    """预设清单（name/description/builtin——壳/CLI 列表用）。"""
    out = []
    for name, p in sorted(load_all(workdir).items()):
        out.append({"name": name, "description": p["description"],
                    "builtin": name in _BUILTIN})
    return out


def list_with_state(workdir=None) -> list[dict]:
    """E2-UI：预设清单 + 解析态（chain/hash/error——壳「装配」分区用）。

    损坏预设不抛错：error 带原因入列（可见性；resolve 仍会对运行期严格拒绝）。
    """
    out = []
    for p in list_presets(workdir):
        item = dict(p)
        try:
            r = resolve(workdir, p["name"])
            item.update(chain=list(r["chain"]), hash=str(r["hash"]), error="")
        except ValueError as exc:
            item.update(chain=[], hash="", error=str(exc))
        out.append(item)
    return out


def _dedup(items) -> list[str]:
    seen: set[str] = set()
    out = []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def resolve(workdir, name: str) -> dict:
    """解析预设（继承链 + 深合并）→ {name, chain, resolved, hash, description}。"""
    all_p = load_all(workdir)
    nm = str(name or "standard") or "standard"
    if nm not in all_p:
        raise ValueError(f"未知预设：{nm}")
    chain: list[str] = []
    seen: set[str] = set()
    cur = nm
    while cur:
        if cur in seen:
            raise ValueError(f"预设继承成环：{'→'.join(chain + [cur])}")
        if cur not in all_p:
            raise ValueError(f"未知 extends：{cur}（来自 {chain[-1] if chain else nm}）")
        seen.add(cur)
        chain.append(cur)
        cur = all_p[cur]["extends"]
    merged: dict = {
        "extensions": {"enable": [], "disable": []},
        "tools": None,
        "prompt_segments": {"disable": []},
        "skills": {"disable": []},
    }
    for layer in reversed(chain):   # 父 → 子
        p = all_p[layer]
        merged["extensions"]["enable"] += p["extensions"]["enable"]
        merged["extensions"]["disable"] += p["extensions"]["disable"]
        if p["tools"] is not None:
            merged["tools"] = list(p["tools"])
        merged["prompt_segments"]["disable"] += p["prompt_segments"]["disable"]
        merged["skills"]["disable"] += p["skills"]["disable"]
    merged["extensions"]["enable"] = _dedup(merged["extensions"]["enable"])
    merged["extensions"]["disable"] = _dedup(merged["extensions"]["disable"])
    merged["prompt_segments"]["disable"] = _dedup(
        merged["prompt_segments"]["disable"])
    merged["skills"]["disable"] = _dedup(merged["skills"]["disable"])
    digest = hashlib.sha256(
        json.dumps(merged, sort_keys=True, ensure_ascii=False)
        .encode("utf-8")).hexdigest()[:12]
    return {"name": nm, "chain": chain, "resolved": merged, "hash": digest,
            "description": all_p[nm]["description"]}


def resolve_for_session(workdir, *, session: str = "",
                        default: str = "standard") -> dict:
    """运行期解析：会话 sidecar > 配置默认；任何失败回退 standard（不阻断）。"""
    try:
        bound = load_session(workdir).get(str(session or ""))
    except Exception:
        bound = None
    for cand in (bound, default, "standard"):
        if not cand:
            continue
        try:
            return resolve(workdir, str(cand))
        except ValueError:
            continue
    return resolve(workdir, "standard")


def session_path(workdir) -> pathlib.Path:
    return pathlib.Path(workdir) / ".wuxing" / _SESSION_FILE


def load_session(workdir) -> dict:
    p = session_path(workdir)
    with lock_for(p):
        if not p.is_file():
            return {}
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}


def save_session(workdir, session: str, name: str) -> dict:
    """写会话绑定（`""` → 清除该会话绑定）。"""
    p = session_path(workdir)
    with lock_for(p):
        data = load_session(workdir)
        key = str(session or "")
        if str(name or ""):
            data[key] = str(name)
        else:
            data.pop(key, None)
        data["updated_at"] = round(time.time(), 3)
        p.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(p, json.dumps(data, ensure_ascii=False, indent=2))
        return data
