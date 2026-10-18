"""提示词分节与节级哈希（E2-3 · ⑰——PP1/CC6）。

- 节级化：system 段由具名节组成（`prompt_builder.system_sections()`），join 即
  `build_system_text`——节粒度 = 缓存前缀断层诊断粒度；
- 稳定标注（CC6）：`static`（代码/域配置才变）/ `unit`（单元参数）/ `session`
  （会话数据）/ `task`（每碎片）——标注只读，不参与装配决策；
- 节级哈希：装配后按节/段计算短哈希（sha256[:12]）→ trace `prompt_sections`
  （缓存 miss 归因：哪一节变了）；
- 差量助手：`diff_sections(prev, cur)` → changed/added/removed（离线/测试用；
  运行时不持有状态——逐事件对比即可）。
"""
import hashlib

_SEGMENT_PREFIXES = (
    ("digest", "[上一轮碎片上下文]"),
    ("history", "[会话历史]"),
    ("skills", "可用技能："),
    ("shared", "[同任务已完成碎片的经验]"),
)


def hash_text(text) -> str:
    """短哈希（sha256 前 12 位）——节/段内容指纹。"""
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()[:12]


def hash_sections(sections) -> dict:
    """节列表（dict{name,text} 或 (name, stability, text)）→ {name: hash}。"""
    out = {}
    for s in sections or ():
        if isinstance(s, dict):
            out[str(s.get("name") or "")] = hash_text(s.get("text"))
        else:
            out[str(s[0])] = hash_text(s[2])
    return out


def diff_sections(prev: dict, cur: dict) -> dict:
    """节级差异（离线/测试用）：changed / added / removed（排序）。"""
    prev, cur = dict(prev or {}), dict(cur or {})
    return {
        "changed": sorted(k for k in cur if k in prev and prev[k] != cur[k]),
        "added": sorted(k for k in cur if k not in prev),
        "removed": sorted(k for k in prev if k not in cur),
    }


def segment_name(content, role: str = "") -> str:
    """消息段名（S4-S9 诊断面）：按前缀分类；未知 user → prompt。"""
    text = str(content or "")
    if role == "system":
        return "system"
    for name, prefix in _SEGMENT_PREFIXES:
        if text.startswith(prefix):
            return name
    if role == "user":
        return "prompt"
    return f"other-{role or '?'}"


def message_hashes(messages) -> dict:
    """消息序列 → {段名: 哈希}（同名多段以 #2 起编号；system 跳过——由节哈希承载）。"""
    out, seen = {}, {}
    for m in messages or ():
        if str(m.get("role") or "") == "system":
            continue
        name = segment_name(m.get("content"), m.get("role"))
        seen[name] = seen.get(name, 0) + 1
        if seen[name] > 1:
            name = f"{name}#{seen[name]}"
        out[name] = hash_text(m.get("content"))
    return out
