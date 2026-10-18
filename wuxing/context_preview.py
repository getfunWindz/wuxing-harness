"""上下文投影（B 期）：下次运行注入的确定性镜像 + 激进上界估算 + trace 实测锚点。

设计：`docs/WUXING_上下文窗口自选_B期设计_2026-09-22.md` §2。
纪律：
  - **投影复用真实装配函数**（ConversationState.context_text/turn_block / prompt_builder）——防漂移；
  - **无数据不造假**：无窗口/无记录 → available=False 或不下发该段；
  - **激进上界估算**（CJK ×2 / 其他 ÷3 + 段开销；宁可偏高不可低估——DSH 官方警告
    `chars/4` 对 CJK 严重低估）；composition 未知的实测段按 CJK 上界（×2）计；
  - system/skills 的运行期真实段长由 trace（`unit_started.system_chars` 等）提供——
    预览不重建工具表（不触发 MCP 装载）；
  - 本模块属引擎包，**不得依赖 wuxing.shell.***（边界纪律）。
"""
from __future__ import annotations

import json
import math
import pathlib

from wuxing.context_sources import content_fp
from wuxing.conversation import ConversationState
from wuxing.prompt_builder import build_skill_index_msg
from wuxing.trace import TraceLogger

# 激进上界常量（显示层口径；如需校准只改常量，不改口径）
CJK_TOKENS_PER_CHAR = 2.0
ASCII_CHARS_PER_TOKEN = 3.0
SEGMENT_OVERHEAD = 8

_UNKNOWN_SEGMENTS = [
    {"key": "task_prompt", "label": "任务与引用（提交时确定）"},
    {"key": "shared", "label": "同任务共享经验（运行期产生）"},
]


def _is_cjk(ch: str) -> bool:
    o = ord(ch)
    return (0x3400 <= o <= 0x4DBF or 0x4E00 <= o <= 0x9FFF
            or 0xF900 <= o <= 0xFAFF or 0x3000 <= o <= 0x303F
            or 0xFF00 <= o <= 0xFFEF)


def _raw_tokens(text: str) -> float:
    s = str(text or "")
    cjk = sum(1 for ch in s if _is_cjk(ch))
    return cjk * CJK_TOKENS_PER_CHAR + (len(s) - cjk) / ASCII_CHARS_PER_TOKEN


def estimate_tokens(text: str) -> int:
    """激进上界 token 估算（空文本 0；非空 + 段开销）。"""
    if not text:
        return 0
    return math.ceil(_raw_tokens(text)) + SEGMENT_OVERHEAD


def _fill_tokens(tokens: int) -> str:
    """构造占位文本，使其 estimate_tokens 恰为 tokens（预算同源计算用；非展示）。

    tokens 含段开销：主体 = 「汉」×c（每个 2 token），余 1 用 3 个 ASCII 字符补齐。
    """
    t = int(tokens) - SEGMENT_OVERHEAD
    if t <= 0:
        return ""
    c, r = divmod(t, 2)
    return "汉" * c + ("abc" if r else "")


def _seg(key: str, label: str, text: str, reference: bool = False,
         detail: str = "") -> dict:
    return {"key": key, "label": label, "chars": len(text),
            "est_tokens": estimate_tokens(text),
            "reference": reference, "detail": detail}


def _seg_raw(key: str, label: str, chars: int, raw: float,
             reference: bool = False, detail: str = "") -> dict:
    """段（字符数已知、原文未持有）：raw=已知 composition 的原始 token；未知按 CJK 上界。"""
    chars = int(chars)
    tokens = math.ceil(raw) + SEGMENT_OVERHEAD if chars > 0 else 0
    return {"key": key, "label": label, "chars": chars, "est_tokens": tokens,
            "reference": reference, "detail": detail}


def _seg_val(key: str, label: str, chars: int, tokens: int,
             reference: bool = False, detail: str = "") -> dict:
    """段（字符数 + 已知 token 估算——如 trace 实测 system 段）。"""
    chars = int(chars)
    return {"key": key, "label": label, "chars": chars,
            "est_tokens": int(tokens) if chars > 0 else 0,
            "reference": reference, "detail": detail}


def _read_jsonl(path: pathlib.Path) -> list:
    """会话存档读取（损坏行跳过；缺文件空——与引擎韧性惯例一致）。"""
    if not pathlib.Path(path).is_file():
        return []
    out = []
    try:
        for line in pathlib.Path(path).read_text(
                encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                out.append(row)
    except OSError:
        return []
    return out


def _rows(workdir) -> list:
    return TraceLogger(pathlib.Path(workdir) / ".wuxing" / "trace.jsonl").load()


def _state_root(engine):
    """E3-1/R5（T2）：引擎状态根（缺省=workdir；兼容无该属性的假引擎）。"""
    return getattr(engine, "state_root", None) or engine.workdir


def _system_measured(rows: list, round_no: int | None = None,
                     unit_id: str | None = None) -> tuple:
    """trace 实测 system 段（unit_started）→ (chars, est_tokens, domains, unit)。

    est_tokens 优先取 trace 的 system_est_tokens（与 runner 同源估算器——预算映射
    与真实装配同口径）；旧 trace 无该字段 → CJK 上界（×2 + 段开销，宁可偏高）。
    """
    best, best_tokens, domains, who = 0, 0, [], ""
    for r in rows:
        if r.get("event") != "unit_started":
            continue
        if unit_id is not None and str(r.get("unit_id") or "") != unit_id:
            continue
        if unit_id is None and round_no is not None:
            try:
                if int(r.get("conversation_round") or -1) != int(round_no):
                    continue
            except (TypeError, ValueError):
                continue
        try:
            chars = int(r.get("system_chars") or 0)
        except (TypeError, ValueError):
            chars = 0
        try:
            est = int(r.get("system_est_tokens") or 0)
        except (TypeError, ValueError):
            est = 0
        if est <= 0 and chars > 0:
            est = chars_raw_upper(chars) + SEGMENT_OVERHEAD
        if chars > best:
            best, best_tokens = chars, est
            who = str(r.get("unit_id") or "")
        dom = str(r.get("domain") or "")
        if dom and dom not in domains:
            domains.append(dom)
    return best, best_tokens, domains, who


def _anchor_measured(rows: list, round_no: int | None = None,
                     unit_id: str | None = None) -> dict:
    """trace 实测锚点（llm_call.input 最大者）——对照行，不混入百分比。"""
    best = None
    for r in rows:
        if r.get("event") != "llm_call":
            continue
        if unit_id is not None and str(r.get("unit_id") or "") != unit_id:
            continue
        if unit_id is None and round_no is not None:
            try:
                if int(r.get("conversation_round") or -1) != int(round_no):
                    continue
            except (TypeError, ValueError):
                continue
        try:
            tokens = int(r.get("input") or 0)
        except (TypeError, ValueError):
            continue
        if tokens <= 0:
            continue
        if best is None or tokens > best["tokens"]:
            best = {"tokens": tokens,
                    "ts": float(r.get("ts") or 0),
                    "unit": str(r.get("unit_id") or "")}
    return best or {"tokens": None, "ts": None, "unit": ""}


def _window(engine) -> int:
    from wuxing.context_window import resolve_context_window
    cfg = engine.cfg
    return resolve_context_window(
        getattr(cfg, "llm", None),
        getattr(cfg, "model_context_windows", None),
        getattr(cfg, "default_context_window", 200_000))


def context_band(percent: float, golden_pct: float = 0.2,
                 managed_pct: float = 0.5) -> str:
    """档位（双模式批 2 · 设计 §6）：≤golden 黄金 / ≤managed 正常 / >managed 严管。"""
    try:
        p = float(percent)
    except (TypeError, ValueError):
        p = 0.0
    if p <= golden_pct:
        return "golden"
    if p <= managed_pct:
        return "normal"
    return "managed"


def _thresholds(engine) -> tuple[float, float]:
    """档位阈值（cfg 读取；非法/缺失 → 默认 0.2/0.5——读侧防御）。"""
    cfg = engine.cfg

    def _f(key: str, fallback: float) -> float:
        try:
            v = float(getattr(cfg, key, fallback))
        except (TypeError, ValueError):
            return fallback
        return v if v > 0 else fallback

    golden = _f("context_golden_pct", 0.2)
    managed = _f("context_managed_pct", 0.5)
    if not (0 < golden < managed <= 1):
        return 0.2, 0.5
    return golden, managed


def _skills_text(engine) -> str | None:
    """技能索引文本（与真实装配同一函数——段长/预算口径同源）。"""
    msg = build_skill_index_msg(getattr(engine, "skills", None))
    if msg is None:
        return None
    return str(msg.get("content") or "")


def _skills_seg(engine) -> dict | None:
    text = _skills_text(engine)
    if text is None:
        return None
    return _seg("skills", "技能索引", text)


def _finalize(segments: list, rounds: list, window: int, anchor: dict,
              sources: dict | None = None, budget_tokens: int = 0,
              trimmed: list | None = None,
              golden_pct: float = 0.2, managed_pct: float = 0.5,
              **head) -> dict:
    total = sum(s["est_tokens"] for s in segments)
    percent = round(total / window, 4) if window > 0 else 0.0
    out = {
        "window": int(window),
        "est_tokens": int(total),
        "percent": percent,
        "band": context_band(percent, golden_pct, managed_pct),
        "golden_pct": golden_pct,
        "managed_pct": managed_pct,
        "segments": segments,
        "rounds": rounds,
        "messages": [],
        "anchor_tokens": anchor.get("tokens"),
        "anchor_ts": anchor.get("ts"),
        "anchor_unit": anchor.get("unit", ""),
        "unknown": [dict(u) for u in _UNKNOWN_SEGMENTS],
        "sources": dict(sources or _all_on()),
        "budget_tokens": int(budget_tokens),
        "trimmed": [dict(t) for t in (trimmed or [])],
        "available": True,
        "reason": "",
    }
    out.update(head)
    return out


def _all_on() -> dict:
    return {"history": True, "digest": True, "skills": True,
            "prefix": True, "budget_tokens": 0}


_SEG_PREFIX = {"history": "[会话历史]", "digest": "[上一轮碎片上下文]",
              "skills": "可用技能："}


def _apply_budget(segments: list, sys_tokens: int, texts: dict,
                  budget: int) -> tuple:
    """预览侧预算裁剪（与 runner 同一 `enforce_budget`——口径同源）。

    system 无原文 → 占位其「实测估算」（旧 trace 为 CJK 上界）；
    返回 (segments, trimmed)。
    """
    from wuxing.context_budget import enforce_budget
    synth: list = []
    if sys_tokens > 0:
        synth.append({"role": "system", "content": _fill_tokens(sys_tokens)})
    if texts.get("digest"):
        synth.append({"role": "user", "content": texts["digest"]})
    if texts.get("history"):
        synth.append({"role": "user", "content": texts["history"]})
    synth.append({"role": "user", "content": "（未提交任务）"})
    if texts.get("skills"):
        synth.append({"role": "user", "content": texts["skills"]})
    kept, trimmed = enforce_budget(synth, int(budget), estimate_tokens)
    out: list = []
    for s in segments:
        key = s["key"]
        if key == "system":
            out.append(s)
            continue
        prefix = _SEG_PREFIX.get(key)
        if prefix is None:
            out.append(s)
            continue
        match = next((m for m in kept
                      if str(m.get("content", "")).startswith(prefix)), None)
        if match is None:
            continue
        out.append(_seg(key, s["label"], str(match.get("content", "")),
                        reference=bool(s.get("reference")),
                        detail=str(s.get("detail", ""))))
    return out, trimmed


def preview_conversation(engine, conversation_path) -> dict:
    """主会话投影（复用 context_text/prev_digest 真值 + trace 实测参考 + 来源开关）。"""
    path = pathlib.Path(conversation_path)
    from wuxing.context_sources import resolve as _resolve_sources
    cfg = engine.cfg
    golden, managed = _thresholds(engine)
    src = _resolve_sources(
        _state_root(engine), conversation=path.name,
        default_budget=int(getattr(cfg, "context_budget_tokens", 0) or 0))
    if not path.is_file():
        return {"session": path.name, "unit_id": "", "window": 0,
                "est_tokens": 0, "percent": 0.0,
                "band": "", "golden_pct": golden, "managed_pct": managed,
                "segments": [], "rounds": [],
                "messages": [],
                "anchor_tokens": None, "anchor_ts": None, "anchor_unit": "",
                "unknown": [], "sources": src, "budget_tokens": 0,
                "trimmed": [], "available": False,
                "reason": "会话文件不存在"}
    state = ConversationState(path)
    rows = _rows(_state_root(engine))
    segments = []
    _texts: dict = {}
    if src["history"]:
        history = state.context_text(getattr(cfg, "conversation_max_chars", 4000))
        if history:
            _texts["history"] = history
            segments.append(_seg("history", "会话历史", history,
                                 detail=f"{state.round_no} 轮"))
    if src["digest"] and bool(getattr(cfg, "fsc_enabled", False)) \
            and bool(getattr(cfg, "fsc_fallback_digest", True)):
        digest = state.prev_digest() or ""
        if digest:
            digest = digest[:int(getattr(cfg, "fsc_digest_max_chars", 2000))]
            _texts["digest"] = digest
            segments.append(_seg("digest", "FSC 回退摘要", digest, reference=True))
    if src["skills"]:
        _smsg = build_skill_index_msg(getattr(engine, "skills", None))
        if _smsg is not None:
            _stext = str(_smsg.get("content") or "")
            _texts["skills"] = _stext
            segments.append(_seg("skills", "技能索引", _stext))
    sys_chars, sys_tokens, domains, _who = _system_measured(
        rows, round_no=state.round_no)
    if sys_chars > 0:
        segments.append(_seg_val(
            "system", "域模板（按上次运行）", sys_chars, sys_tokens,
            reference=True,
            detail="、".join(domains[:4]) + "（取最大单元）"))
    budget = int(src.get("budget_tokens") or 0)
    budget_auto = False
    _w = _window(engine)
    if budget <= 0:
        from wuxing.context_budget import auto_trigger_budget, trim_target
        _trigger = auto_trigger_budget(cfg, _w)
        if _trigger > 0 and sum(s["est_tokens"] for s in segments) > _trigger:
            budget = trim_target(cfg, _w, _trigger)
            budget_auto = True
    trimmed: list = []
    if budget > 0:
        segments, trimmed = _apply_budget(segments, sys_tokens, _texts, budget)
    return _finalize(segments, state.turn_views(estimator=estimate_tokens),
                     _w,
                     _anchor_measured(rows, round_no=state.round_no),
                     sources=src, session=path.name, unit_id="",
                     budget_tokens=budget, trimmed=trimmed,
                     budget_auto=budget_auto,
                     golden_pct=golden, managed_pct=managed)


def chars_raw_upper(chars: int) -> float:
    """composition 未知的实测段 → CJK 上界（×2）。"""
    return int(chars) * CJK_TOKENS_PER_CHAR


def preview_unit(engine, unit_id: str) -> dict:
    """碎片会话投影（FSC 保留前缀 + 域模板实测 + 技能索引；来源开关生效）。"""
    uid = str(unit_id or "").strip()
    golden, managed = _thresholds(engine)
    from wuxing.context_sources import resolve as _resolve_sources
    src = _resolve_sources(
        _state_root(engine), unit=uid,
        default_budget=int(getattr(engine.cfg, "context_budget_tokens", 0) or 0))
    empty = {"session": "", "unit_id": uid, "window": 0, "est_tokens": 0,
             "percent": 0.0,
             "band": "", "golden_pct": golden, "managed_pct": managed,
             "segments": [], "rounds": [], "messages": [],
             "anchor_tokens": None, "anchor_ts": None, "anchor_unit": "",
             "unknown": [], "sources": src, "budget_tokens": 0,
             "trimmed": [], "available": False,
             "reason": "无该碎片会话记录"}
    if not uid:
        return empty
    sess = pathlib.Path(_state_root(engine)) / ".wuxing" / "sessions"
    files = []
    if sess.is_dir():
        files = [sess / f"{uid}.jsonl"] + sorted(sess.glob(f"*-{uid}.jsonl"))
        files = [p for p in files if p.is_file()]
    rows = _rows(_state_root(engine))
    has_trace = any(str(r.get("unit_id") or "") == uid for r in rows)
    if not files and not has_trace:
        return empty
    chars, msgs, raw = 0, 0, 0.0
    items: list = []
    for p in files:
        for row in _read_jsonl(p):
            for m in (row.get("messages") or []):
                content = str((m or {}).get("content") or "")
                items.append({"file": p.name, "index": len(items),
                              "role": str((m or {}).get("role") or ""),
                              "state": str(row.get("state") or ""),
                              "content": content,
                              "fp_in": content_fp(content), "fp_out": ""})
    # 输出侧代表指纹：首个 thinking 非工具内容；其余（提示词侧/工具行）用该指纹
    _out_first = ""
    for it in items:
        if (it["state"] == "thinking" and it["role"] != "system"
                and not it["content"].startswith("[tool]")):
            _out_first = it["fp_in"]
            break
    for it in items:
        is_output = (it["state"] == "thinking" and it["role"] != "system"
                     and not it["content"].startswith("[tool]"))
        it["fp_out"] = it["fp_in"] if is_output else _out_first
    # A2：unit 投影层编辑（omit/replace；双指纹任一命中）——面板/E2E 与注入同源
    from wuxing.context_edits import apply_unit_edits
    from wuxing.context_sources import load_unit_edits
    _edits = load_unit_edits(_state_root(engine), uid)
    _orig = {it["index"]: it["content"] for it in items}
    if _edits:
        eff, _skipped = apply_unit_edits([dict(it) for it in items], _edits)
        eff_by_idx = {it["index"]: it["content"] for it in eff}
        for it in items:
            if it["index"] not in eff_by_idx:
                it["omitted"], it["replaced"] = True, False
            else:
                it["omitted"] = False
                it["content"] = eff_by_idx[it["index"]]
                it["replaced"] = it["content"] != _orig[it["index"]]
    else:
        for it in items:
            it["omitted"] = it["replaced"] = False
    kept = [it for it in items if not it["omitted"]]
    sys_chars, sys_tokens, domains, who = _system_measured(rows, unit_id=uid)
    # A3：预算裁剪（与 runner 同源；system 实测估算占位 + 技能真实文本 + 索引映射）
    budget = int(src.get("budget_tokens") or 0)
    budget_auto = False
    if budget <= 0:
        from wuxing.context_budget import auto_trigger_budget, trim_target
        _w2 = _window(engine)
        _trigger2 = auto_trigger_budget(engine.cfg, _w2)
        if _trigger2 > 0:
            _est_unit = sys_tokens + sum(
                estimate_tokens(it["content"]) for it in kept)
            if _est_unit > _trigger2:
                budget = trim_target(engine.cfg, _w2, _trigger2)
                budget_auto = True
    trimmed: list = []
    if budget > 0 and kept:
        from wuxing.context_budget import enforce_budget_indexed
        owners: list = []
        synth: list = []
        if sys_tokens > 0:
            synth.append({"role": "system", "content": _fill_tokens(sys_tokens)})
            owners.append(None)
        for it in kept:
            synth.append({"role": "user", "content": it["content"]})
            owners.append(it)
        synth.append({"role": "user", "content": "（未提交任务）"})
        owners.append(None)
        _sk_text = _skills_text(engine) if src["skills"] else None
        if _sk_text:
            synth.append({"role": "user", "content": _sk_text})
            owners.append(None)
        _, trimmed, kept_pos = enforce_budget_indexed(
            synth, budget, estimate_tokens)
        kept = [owners[p] for p in kept_pos if owners[p] is not None]
    kept_contents = [it["content"] for it in kept]
    chars = sum(len(c) for c in kept_contents)
    raw = sum(_raw_tokens(c) for c in kept_contents)
    msgs = len(kept_contents)
    messages = [{"index": it["index"], "role": it["role"],
                 "text": it["content"][:400],
                 "fp_in": it["fp_in"], "fp_out": it["fp_out"],
                 "omitted": bool(it["omitted"]),
                 "replaced": bool(it["replaced"])} for it in items][-100:]
    segments = []
    if src["prefix"] and chars > 0:
        segments.append(_seg_raw("fsc_prefix", "碎片会话前缀", chars, raw,
                                 reference=True,
                                 detail=f"{msgs} 条消息 / {len(files)} 个文件"))
    if sys_chars > 0:
        segments.append(_seg_val(
            "system", "域模板（按上次运行）", sys_chars, sys_tokens,
            reference=True,
            detail="、".join(domains[:2]) + (f" · {who}" if who else "")))
    if src["skills"]:
        skills = _skills_seg(engine)
        if skills is not None:
            segments.append(skills)
    return _finalize(segments, [], _window(engine),
                     _anchor_measured(rows, unit_id=uid),
                     sources=src, session="", unit_id=uid,
                     messages=messages, budget_tokens=budget, trimmed=trimmed,
                     budget_auto=budget_auto,
                     golden_pct=golden, managed_pct=managed)
