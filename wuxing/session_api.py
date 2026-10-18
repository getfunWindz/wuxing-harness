"""会话 API（B 模式：同一任务内多轮交互的公开入口）。

ConversationSession = Engine 的会话句柄：
  send(user_text) → 一次碎片 DAG 执行（携带会话历史前缀）→ 追加轮次记录
  round_no / artifacts() / metrics() → 会话状态查询

设计语义：
  - 轮内一致：run_task 期间会话段不变（append 在轮次完成后——跨碎片前缀共享）
  - 前缀只增：历史轮次内容永不改写（服务端缓存命中前提）
  - 交付物累计：跨轮 artifacts 去重累计（后续轮次可见/可注入）
"""
import time

from wuxing.events import UnitReasoning


def collect_turn_artifacts(res) -> list:
    """本轮交付物（真实 deliverables ∪ 契约 artifacts；去重保序）。"""
    arts, seen = [], set()
    real = [d for u in (getattr(res, "units", None) or [])
            for d in (getattr(u, "deliverables", None) or [])]
    for p in (real + [a.path for a in (getattr(res, "artifacts", None) or [])]):
        if p and p not in seen:
            seen.add(p)
            arts.append(p)
    return arts


def build_turn_summary(res, arts: list | None = None) -> str:
    """机械轮次摘要（status + 交付物前三个）——send/终态重写共用。"""
    if arts is None:
        arts = collect_turn_artifacts(res)
    summary = str(getattr(res, "status", ""))
    if arts:
        summary += f"；交付物 {', '.join(arts[:3])}"
    return summary


def collect_turn_reply(res) -> str:
    """本轮模型总体回复（Task 4-2）：最后一个非空单元 reply（空→不落键）。"""
    reply = ""
    for u in (getattr(res, "units", None) or []):
        text = str(getattr(u, "reply", "") or "").strip()
        if text:
            reply = text
    return reply


def reply_for_turn(engine, res) -> str:
    """本轮总体回复（Task A2）：引擎生成优先（pi 式）；失败/关闭 → 单元回退。

    生成由 Engine.generate_task_reply 提供（终端状态 + 开关 + 字符上限）；
    引擎不支持/生成失败/开关关闭 → 最后非空单元 reply（collect_turn_reply）。
    """
    gen = getattr(engine, "generate_task_reply", None)
    if callable(gen):
        try:
            text = str(gen(res) or "").strip()
        except Exception:
            text = ""
        if text:
            return text
    return collect_turn_reply(res)


def collect_turn_thoughts(captured: list) -> list:
    """本轮思维链（Task 4-2）：UnitReasoning 事件 → 行载荷（cap 30 条）。"""
    thoughts = [
        {"unit_id": str(getattr(ev, "unit_id", "")),
         "round": int(getattr(ev, "round", 0) or 0),
         "text": str(getattr(ev, "text", ""))[:4000]}
        for ev in captured
        if str(getattr(ev, "text", "") or "").strip()
    ]
    return thoughts[-30:]


class ConversationSession:
    """会话句柄（由 Engine.start_session 创建——勿直接构造）。"""

    def __init__(self, engine, state):
        self.engine = engine
        self.state = state
        self._round_metrics = []  # [{round, status, usage, cache_read_ratio}]

    @property
    def round_no(self) -> int:
        return self.state.round_no

    def artifacts(self) -> list:
        return self.state.artifacts()

    def send(self, user_text: str, on_event=None, references=None, unit="",
             overrides=None):
        """一轮交互：执行 + 记录轮次（返回 TaskResult，metrics 附会话信息）。

        on_event/references（2026-09-20 壳接入）：转发 run_task——Web 提交链路复用本路径。
        unit（碎片会话后半程 2026-09-22）：碎片会话内提交的轮次标记——
        该轮不计入主会话上下文窗口（context_text/prev_digest 跳过）。
        overrides（二期批 1）：显式闸覆盖集透传（无地图执行 override）。
        """
        res = None
        # Task 4-2（思维链实时化）：旁路采集 UnitReasoning（会话行 thoughts 落盘——
        # 完成轮卡片/历史回看数据面）；on_event 原样转发（不改变壳消费）。
        captured: list = []

        def _capture(ev):
            if isinstance(ev, UnitReasoning):
                captured.append(ev)
            if on_event is not None:
                on_event(ev)

        try:
            res = self.engine.run_task(user_text, on_event=_capture,
                                       conversation=self.state,
                                       references=references,
                                       overrides=overrides)
        except Exception as exc:
            # 2026-10-01 真机 P1：失败提交也必须留痕（否则会话里看不到发过什么、
            # 发生了什么——review 不可用；壳 manager 同样会捕获并上报 task_failed）。
            self.state.append_turn(
                self.state.round_no + 1, user_text, [],
                f"error：{type(exc).__name__}: {exc}"[:300], unit=unit)
            raise
        # 交付物 = 真实 deliverables（从 units 汇总）+ 契约 artifacts（去重）
        # 韧性（2026-09-20）：TaskResult 契约字段缺失不阻断（夹具/兼容对象）
        arts = collect_turn_artifacts(res)
        summary = build_turn_summary(res, arts)
        # B2（跨轮上下文继承）：采集本轮产物内容摘录（文档类——头 200 字符）
        excerpts = []
        ws = getattr(self.engine, "ws", None)
        if ws is not None:
            for p in arts:
                if len(excerpts) >= 3:
                    break
                if str(p).endswith((".md", ".txt", ".py", ".java", ".js", ".ts",
                                    ".vue", ".json", ".yml", ".yaml")):
                    c = ws.read(p) or ""
                    if c.strip():
                        excerpts.append({"path": p, "excerpt": c[:200]})
        self.state.append_turn(self.state.round_no + 1, user_text, arts, summary,
                               artifact_excerpts=excerpts,
                               fragment_digest=self._turn_digest(res),
                               unit=unit,
                               reply=reply_for_turn(self.engine, res),
                               thoughts=collect_turn_thoughts(captured))
        # 轮次度量（Task 4：累计命中率曲线）
        usage = ((getattr(res, "metrics", None) or {}).get("usage", {}) or {})
        inp = int(usage.get("input", 0) or 0)
        cr = int(usage.get("cache_read", 0) or 0)
        self._round_metrics.append({
            "round": self.state.round_no,
            "status": res.status,
            "usage": dict(usage),
            # 口径修正：零输入轮（无调用/缓存全命中）记 None——不拉低均值
            "cache_read_ratio": round(cr / inp, 4) if inp else None,
            "ts": round(time.time(), 3),
        })
        if getattr(res, "metrics", None) is not None:
            res.metrics["conversation"] = {
                "round": self.state.round_no,
                "cumulative": self.metrics(),
            }
        return res

    def _turn_digest(self, res) -> str:
        """本轮碎片摘要（FSC 低匹配回退——下一轮前缀注入原料；失败不阻断）。"""
        try:
            from wuxing.conversation import build_turn_digest
            return build_turn_digest(
                getattr(res, "fragments", None) or [],
                getattr(res, "units", None) or [],
                max_chars=int(getattr(self.engine.cfg, "fsc_digest_max_chars",
                                      2000) or 2000))
        except (AttributeError, TypeError, ValueError):
            # 摘要生成失败 → 空串（digest 缺失降级）
            return ""

    def metrics(self) -> dict:
        """会话度量：轮次 + 累计 usage + 累计命中率（真实测试口径）。"""
        total = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
        for m in self._round_metrics:
            for k in total:
                total[k] += int((m.get("usage") or {}).get(k, 0) or 0)
        inp, cr = total["input"], total["cache_read"]
        # 口径修正：有效轮均值（剔除零输入轮）——单轮均值失真的修正
        eff = [m["cache_read_ratio"] for m in self._round_metrics
               if m.get("cache_read_ratio") is not None]
        return {
            "rounds": self.round_no,
            "artifacts": self.state.artifacts(),
            "cumulative": {
                "usage": total,
                "cache_read_ratio": round(cr / inp, 4) if inp else 0.0,
            },
            "effective_rounds": len(eff),
            "avg_effective_ratio": round(sum(eff) / len(eff), 4) if eff else 0.0,
            "per_round": list(self._round_metrics),
        }
