"""会话模式 sidecar（双模式批 1 · Task 2；2026-09-23 设计 v1 已复核）。

文件：`<workdir>/.wuxing/session-modes.json`（原子写；缺失/损坏 → 用默认）。
模式 = 会话级固定（创建时确定；仅空白会话可切——缓存前缀纪律，设计 §3.1）。
壳写引擎读（同 `context-sources.json` 模式）；runner 装配点 `resolve`。

模式词汇（二期批 1 · 2026-09-25 更名）：
  - minimal/pure      极简·纯净
  - minimal/standard  极简·标准（默认）
  - theroad           THEROAD / 循迹（无变体——variant 归一为 ""）
兼容读：旧值 "wayfinder" 归一为 "theroad"（读侧归一、写侧新值，不迁移用户文件）。
"""
from __future__ import annotations

import json
import pathlib
import time

from wuxing.atomic_write import atomic_write_text

_FILENAME = "session-modes.json"
MODES = ("minimal", "theroad")
LEGACY_MODES = {"wayfinder": "theroad"}  # 旧值兼容读（写侧新值）
VARIANTS = ("pure", "standard")
DEFAULT_ID = "minimal-standard"


def _normalize_mode(mode) -> str:
    """旧值兼容：wayfinder → theroad（其余原样）。"""
    m = str(mode or "")
    return LEGACY_MODES.get(m, m)


def modes_path(workdir) -> pathlib.Path:
    return pathlib.Path(workdir) / ".wuxing" / _FILENAME


def parse_id(value) -> dict:
    """模式 id（`<mode>-<variant>` 或 `theroad`/旧 `wayfinder`）→ {"mode","variant"}。

    非法值（含 None/空串/minimal 裸名）→ ValueError（早报，不静默）。
    """
    if isinstance(value, str):
        if _normalize_mode(value) == "theroad":
            return {"mode": "theroad", "variant": ""}
        for variant in VARIANTS:
            if value == f"minimal-{variant}":
                return {"mode": "minimal", "variant": variant}
    raise ValueError(f"未知模式 id：{value!r}")


def _valid(mode, variant) -> bool:
    m = _normalize_mode(mode)
    if m == "theroad":
        return variant == ""
    return m == "minimal" and variant in VARIANTS


def load(workdir) -> dict:
    """原始 sidecar（缺失/损坏/非对象 → {}——读侧容错）。"""
    p = modes_path(workdir)
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def resolve(workdir, *, conversation: str = "",
            default: str = DEFAULT_ID) -> dict:
    """有效模式：会话条目合法则优先（source=session）→ 否则默认 id（source=default）。"""
    try:
        out = dict(parse_id(default))
    except ValueError:
        out = dict(parse_id(DEFAULT_ID))  # 程序化非法默认 → 兜底（配置校验已挡）
    out["source"] = "default"
    if conversation:
        bucket = load(workdir).get("conversations")
        if isinstance(bucket, dict):
            item = bucket.get(str(conversation))
            if isinstance(item, dict) and _valid(item.get("mode"),
                                                 item.get("variant")):
                out = {"mode": _normalize_mode(item["mode"]),
                       "variant": item["variant"], "source": "session"}
    return out


def save(workdir, conversation: str, mode: str, variant: str) -> dict:
    """读-改-写（合并保留其他会话；原子替换）。未知 mode/variant → ValueError。

    theroad 变体归一为 ""；旧值 wayfinder 归一为 theroad（写侧新值）。
    返回写入条目（含 ts）。
    """
    name = str(conversation or "").strip()
    if name == "":
        raise ValueError("会话名不能为空")
    mode = _normalize_mode(mode)
    variant = str(variant or "")
    if mode == "theroad":
        variant = ""  # 归一：THEROAD 无变体
    elif not (mode == "minimal" and variant in VARIANTS):
        raise ValueError(f"未知模式/变体：{mode}/{variant}")
    data = load(workdir)
    data.setdefault("version", 1)
    bucket = data.get("conversations")
    if not isinstance(bucket, dict):
        bucket = {}
        data["conversations"] = bucket
    entry = {"mode": mode, "variant": variant, "ts": round(time.time(), 3)}
    bucket[name] = entry
    atomic_write_text(modes_path(workdir),
                      json.dumps(data, ensure_ascii=False, indent=2))
    return dict(entry)


def conversation_is_blank(path) -> bool:
    """空白判据：无 turns（或文件不存在/不可读）→ True（可切换模式）。

    会话日志 append-only；turns 非空即视为非空白（机制守卫，设计 §8）。
    """
    p = pathlib.Path(path)
    if not p.is_file():
        return True
    try:
        from wuxing.conversation import ConversationState
        return len(ConversationState(p).turns) == 0
    except Exception:
        # 会话文件不可读 → 视为空白会话（保守：不误判为有内容）
        return True
