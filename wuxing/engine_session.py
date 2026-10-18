"""Engine 会话/分支子系统（骨架分期 P5/F-3d：自 engine.py 提取的方法组）。

来源：`wuxing/engine.py`（2026-10-06 迁移；方法体逐字节保持）。
理由：F-3 巨型文件分期——会话/分支/设计轮面落隔离模块（S-2 mixin 裁定）；engine 只做类基接线。
依赖：经 `self` 访问引擎状态（workdir/cfg/orchestrator/trace）；**不得 import engine**（守卫）。
"""
import logging
import pathlib
import time

from wuxing.artifacts import result_artifacts
from wuxing.protocols import TaskResult
from wuxing.session_plan import session_plan

logger = logging.getLogger(__name__)


class EngineSessionMixin:
    def preview_session_context(self, conversation_path=None,
                                unit_id: str | None = None) -> dict:
        """上下文投影（B 期）：主会话或碎片会话的「下次运行注入」分段 + 估算。

        只读（无 LLM 调用）；复用真实装配函数（ConversationState/prompt_builder）；
        无数据 available=False（不造假）；估算为激进上界（见 context_preview 模块）。
        """
        from wuxing import context_preview
        if unit_id:
            return context_preview.preview_unit(self, str(unit_id))
        if conversation_path is None:
            return {"session": "", "unit_id": "", "window": 0,
                    "est_tokens": 0, "percent": 0.0, "segments": [],
                    "rounds": [], "anchor_tokens": None, "anchor_ts": None,
                    "anchor_unit": "", "unknown": [],
                    "sources": {"history": True, "digest": True,
                                "skills": True, "prefix": True,
                                "budget_tokens": 0},
                    "budget_tokens": 0, "trimmed": [],
                    "available": False, "reason": "未指定会话"}
        return context_preview.preview_conversation(self, conversation_path)

    def start_session(self, conversation_path=None):
        """B 模式：开启/恢复会话（同一任务内多轮交互——历史前缀累积）。

        会话状态持久化于 workdir/.wuxing/conversation.jsonl；同 workdir 新实例
        自动恢复历史（跨 Engine 会话连续）。
        """
        from wuxing.conversation import ConversationState
        from wuxing.session_api import ConversationSession
        # E3-1/R5（T2）：状态根（缺省=workdir；兼容无 state_root 的假引擎）
        root = getattr(self, "state_root", None) or self.workdir
        path = (pathlib.Path(conversation_path) if conversation_path else
                root / ".wuxing" / "conversation.jsonl")
        state = ConversationState(path)
        self.orchestrator.conversation = state
        return ConversationSession(self, state)

    # ---- G1（对话分支）：派生会话 + 承接摘要 + 血缘 ----

    def branch_conversation(self, source: str, from_round: int,
                            mode: str = "redo", summary: str = "mech",
                            focus: str = "", max_chars: int = 2000) -> dict:
        """从既有会话派生新会话（fork 式；设计 `WUXING_对话分支_G1`）。

        mode: redo（重做第 N 轮——前缀 1..N-1，返回 redo_text 供回填）
              / continue（从第 N 轮之后继续——前缀 1..N）。
        summary: mech（机械·默认）/ llm（模型摘要 + focus；不可用自动降级 mech）
                 / none。
        原会话零改动；新会话 = 前缀行字节复制 + 承接行；血缘落
        `.wuxing/branches.jsonl`（append-only）。
        """
        import json as _json

        from wuxing import conversation as _conv
        from wuxing.atomic_write import atomic_write_text

        if mode not in ("redo", "continue"):
            raise ValueError(f"非法分支模式：{mode!r}（需 redo|continue）")
        if summary not in ("mech", "llm", "none"):
            raise ValueError(f"非法摘要模式：{summary!r}（需 mech|llm|none）")
        try:
            n = int(from_round)
        except (TypeError, ValueError):
            raise ValueError(f"分支轮次非法：{from_round!r}")
        if n < 1:
            raise ValueError(f"分支轮次非法：{from_round!r}")

        base = (getattr(self, "state_root", None) or self.workdir) / ".wuxing"
        raw = str(source or "").strip()
        if not raw:
            raise ValueError("来源会话为空")
        cand = pathlib.Path(raw)
        if cand.is_absolute() or cand.exists():
            src_path = cand
        elif "/" in raw or "\\" in raw or raw in (".", ".."):
            raise ValueError(f"会话不存在：{raw}")
        else:
            src_path = base / (raw if raw.endswith(".jsonl")
                               else raw + ".jsonl")
        if not src_path.is_file():
            raise ValueError(f"会话不存在：{raw}")

        def _rnd(t: dict) -> int:
            try:
                return int(t.get("round") or 0)
            except (TypeError, ValueError):
                # 轮次字段缺失/非法 → 0：排序读侧容错
                return 0

        state = _conv.ConversationState(src_path)
        turn_rows = [t for t in state.turns
                     if "round" in t and not _conv.is_branch_row(t)]
        target = next((t for t in turn_rows if _rnd(t) == n), None)
        if target is None:
            raise ValueError(f"分支轮次越界：第 {n} 轮不存在")
        if str(target.get("unit") or ""):
            raise ValueError(f"第 {n} 轮为碎片轮，不能作为分支点")

        k = n - 1 if mode == "redo" else n
        prefix_lines: list = []
        for line in src_path.read_text(encoding="utf-8",
                                       errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                row = _json.loads(line)
            except ValueError:
                prefix_lines.append(line)  # 破损行原样保留（韧性惯例）
                continue
            if ("round" in row and not _conv.is_branch_row(row)
                    and _rnd(row) > k):
                break
            prefix_lines.append(line)

        lo = n if mode == "redo" else n + 1
        tail = [t for t in turn_rows if _rnd(t) >= lo]

        requested = summary
        if not tail or summary == "none":
            actual, text = "none", ""
        elif summary == "llm" and not self._llm_is_mock():
            try:
                text = self._branch_llm_summary(tail, focus, max_chars)
                actual = "llm"
            except Exception as e:  # 摘要失败不阻断分支（降级可见）
                logger.warning("分支 LLM 摘要失败——降级机械：%s", e)
                actual, text = "mech", _conv.build_branch_digest(
                    tail, max_chars=max_chars)
        else:
            actual, text = "mech", _conv.build_branch_digest(
                tail, max_chars=max_chars)

        branch_row = {"type": "branch", "source": src_path.name,
                      "from_round": n, "mode": mode,
                      "summary_mode": actual, "summary": text,
                      "focus": str(focus or ""), "ts": round(time.time(), 3)}
        base.mkdir(parents=True, exist_ok=True)
        name = _conv.new_conversation_name(base)
        content = "\n".join(prefix_lines + [
            _json.dumps(branch_row, ensure_ascii=False)]) + "\n"
        atomic_write_text(base / name, content)

        lineage = {"conversation": name, "source": src_path.name,
                   "from_round": n, "mode": mode,
                   "summary_mode": actual, "ts": branch_row["ts"]}
        try:
            with open(base / "branches.jsonl", "a", encoding="utf-8") as f:
                f.write(_json.dumps(lineage, ensure_ascii=False) + "\n")
        except OSError as e:  # 血缘=可见性优化：不阻断（但留痕）
            logger.warning("分支血缘写入失败：%s", e)

        # G3：分支作用域——复制分支点前（轮 ≤ K）的源编辑记录（含 restore；原序）
        try:
            src_edits = base / "context-edits.jsonl"
            if src_edits.is_file():
                copied = []
                for line in src_edits.read_text(
                        encoding="utf-8", errors="replace").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = _json.loads(line)
                    except ValueError:
                        continue  # 损坏行跳过（韧性惯例）
                    if str(row.get("conversation") or "") != src_path.name:
                        continue
                    if str(row.get("op") or "") not in ("omit", "replace",
                                                        "restore"):
                        continue
                    try:
                        if int(row.get("round")) > k:
                            continue
                    except (TypeError, ValueError):
                        continue
                    copied.append({**row, "conversation": name})
                if copied:
                    with open(src_edits, "a", encoding="utf-8") as f:
                        f.writelines(
                            _json.dumps(rec, ensure_ascii=False) + "\n"
                            for rec in copied)
        except OSError as e:  # 编辑继承=增强面：不阻断（留痕）
            logger.warning("分支编辑继承失败：%s", e)

        result = {"created": True, "session": name,
                  "path": str((base / name).resolve()),
                  "source": src_path.name, "from_round": n, "mode": mode,
                  "summary_mode_requested": requested, "summary_mode": actual,
                  "summary": text, "prefix_rounds": k,
                  "abandoned_rounds": len(tail)}
        if mode == "redo":
            result["redo_text"] = str(target.get("user_text") or "")
        return result

    def _llm_is_mock(self) -> bool:
        """默认模型是否 Mock（LLM 摘要降级判定——与形状化降级同哲学）。"""
        try:
            spec = self.llm.spec() if hasattr(self.llm, "spec") else ""
        except Exception:
            spec = ""
        return str(spec or "").strip().lower() in ("", "mock")

    def _branch_llm_summary(self, tail: list, focus: str,
                            max_chars: int) -> str:
        """模型摘要（pi 式分支摘要；失败由调用方降级——此处抛错）。"""
        lines = []
        for t in tail:
            rnd = t.get("round", "?")
            text = str(t.get("user_text") or "")[:200]
            sm = str(t.get("summary") or "")[:120]
            lines.append(f"第{rnd}轮：{text}" + (f"（{sm}）" if sm else ""))
        body = "\n".join(lines)[:6000]
        prompt = ("以下是一个被放弃的执行分支（用户已从更早的轮次重新开始）。"
                  "请总结该分支：目标、尝试过的做法、进展与产物、结论与遗留问题。"
                  "不超过 300 字，直接输出总结正文。\n"
                  + (f"额外关注：{focus}\n" if str(focus or "").strip() else "")
                  + "——分支内容——\n" + body)
        from wuxing.usage_tracker import UsageTracker
        _ut = UsageTracker(self.llm)
        _t0 = time.perf_counter()
        _snap = _ut.snapshot()
        try:
            out = self.llm.chat([{"role": "user", "content": prompt}])
        finally:
            # E0-6：分支摘要调用计账（辅助）
            self._record_aux_call("branch_summary", _ut.since(_snap),
                                  t0=_t0)
        text = out if isinstance(out, str) else str(
            getattr(out, "text", None) or out or "")
        text = " ".join(text.split())
        if not text:
            raise ValueError("LLM 摘要为空")
        if max_chars > 0 and len(text) > max_chars:
            text = text[:max(0, max_chars - 1)] + "…"
        return text

    def _fallback_fragments(self, task_text: str) -> list:
        """S6：形状化失败兜底——整段文本单碎片（execute 直干；补 plan 链）。

        透明标记 _shape_fallback（报告归因——真实测试素材）。
        """
        return [{"fragment_id": "F-fallback0", "domain": "execute",
                 "deps": [], "text": task_text, "deliverables": [],
                 "granularity": None, "_shape_fallback": True}]

    # ---- 双模式批 3（循迹）：模式解析 / 闸 / 设计轮 / 地图摘要 ----

    def _session_mode(self, conversation) -> dict:
        """当前会话模式（无会话 → 全局默认）。"""
        from wuxing.session_modes import resolve as _resolve
        name = ""
        conv = conversation or getattr(self.orchestrator, "conversation", None)
        try:
            name = conv.path.name if conv is not None else ""
        except AttributeError:
            name = ""
        return _resolve(self.workdir, conversation=name,
                        default=getattr(self.cfg, "mode_default",
                                        "minimal-standard"))

    def _in_theroad(self, conversation) -> bool:
        return conversation is not None and \
            self._session_mode(conversation)["mode"] == "theroad"

    def _claim_holder(self, conversation) -> str:
        """G8：票据认领归属（会话文件名；无会话 → cli——headless）。"""
        try:
            name = conversation.path.name if conversation is not None else ""
        except AttributeError:
            name = ""
        return str(name or "cli")

    def _theroad_design_needed(self, conversation) -> bool:
        """引擎闸（设计 §5.2 + 批 3/4 拓宽）：theroad 仍在设计流 → 设计轮。

        设计流判据：
          - 已交接口（phase=ready）→ False（用户显式交接口 = 设计完成）；
          - 地图不可用 → True（侦察/拷问）；
          - 规格未收敛 → True（批 3：spec 阶段）；
          - 实施票据未发布（无 ready）→ True（批 4：提议/quiz 阶段）；
          - 地图 + 规格 + ready 票据 → False（执行；批 5 接票据编排）。
        headless（conversation is None）不拦截——设计 §8「循迹需交互界面」回落。
        显式 override 由调用方（run_task）跳过本闸。
        """
        if not self._in_theroad(conversation):
            return False
        name = ""
        try:
            name = conversation.path.name if conversation is not None else ""
        except AttributeError:
            name = ""
        plan = session_plan(self.workdir, name, default_mode=str(
            getattr(self.cfg, "mode_default", "minimal-standard")))
        return plan["kind"] == "design"

    def _conv_name(self) -> str:
        try:
            conv = getattr(self.orchestrator, "conversation", None)
            return conv.path.name if conv is not None else ""
        except AttributeError:
            # orchestrator/conversation 未装配 → 空串（诊断字段容错）
            return ""

    @staticmethod
    def _design_reply(units) -> str:
        """设计单元回复文本（logs 反扫——跳过工具/守卫日志行与空文本）。

        真测 REAL-8：末轮空文本（纯工具轮）会被 logs.append("") 记入——
        若不过滤空串，逆扫第一命中就是它，上一轮合规的【票据】/【决策】被遮蔽丢失。
        """
        for u in units or []:
            for entry in reversed(getattr(u, "logs", None) or []):
                s = str(entry).strip()
                if not s or s.startswith(("[tool", "[guard", "[warn")):
                    continue
                return s
        return ""

    def _run_design_round(self, task_text, on_event, token) -> TaskResult:
        """循迹设计轮（侦察/拷问/地图）：合成 design 碎片 → 更新设计态 →
        NeedsDesign（可见）。**不写** task_state（不污染执行断点恢复）。"""
        from wuxing import design_state
        from wuxing.domains.defaults import DESIGN_DOMAIN
        from wuxing.map_doc import append_decision, file_hash, is_usable, map_path
        self.registry.register("design", DESIGN_DOMAIN)
        st = design_state.load(self.workdir)
        # G8：认领视图注入（陈旧认领——agent 向用户确认后经 unclaim_ticket 释放）
        from wuxing import tickets as _tickets_dr
        _design_text = design_state.brief(self.workdir, st)
        _claims_text = _tickets_dr.claims_note(self.workdir)
        if _claims_text:
            _design_text += "\n\n" + _claims_text
        old_phase = str(st.get("phase") or "")
        old_spec = str(st.get("spec_slug") or "")
        _mp = map_path(self.workdir)
        old_hash = file_hash(_mp) if _mp.is_file() else ""
        round_no = int(st.get("round") or 0) + 1
        frag = {"fragment_id": f"D-{round_no}", "domain": "design",
                "deps": [], "deliverables": [],
                "text": _design_text + "\n\n用户输入：" + task_text}
        snap = self._task_start_snapshot()
        units = self.orchestrator.run([frag], task_text, on_event=on_event,
                                      cancel=token, references_text="")
        reply = self._design_reply(units)
        qs = design_state.parse_questions(reply)
        facts = design_state.parse_facts(reply)
        # 批 2：【决策】块 → 关闭票据 + 决策入地图（分岔 append）；新问题→新票据
        decisions = design_state.parse_decisions(reply)
        tks = design_state.tickets(st)
        head = str(st.get("branch_head") or "")
        closed: list[tuple[str, str]] = []
        drift_new: list[dict] = []
        for d in decisions:
            entry = append_decision(
                self.workdir, text=d["text"], why=d.get("why", ""),
                upstream=(d.get("rollback") or head or ""),
                supersedes=(head if d.get("rollback") and head else ""),
                source=d.get("ticket", ""))
            head = entry["id"]
            tid = str(d.get("ticket") or "")
            if tid:
                hit = next((x for x in tks if str(x.get("id")) == tid), None)
                if hit is not None:
                    tks = [x for x in tks if str(x.get("id")) != tid]
                else:
                    # C5 机械校验：关闭未知/重复票据 → 漂移可见（决策仍入图——不丢信息）
                    drift_new.append({
                        "round": round_no, "kind": "unknown-ticket", "id": tid,
                        "detail": f"决策引用了未打开的票据：{str(d['text'])[:40]}",
                        "ts": round(time.time(), 3)})
            closed.append((tid or entry["id"], d["text"]))
        created: list[dict] = []
        next_no = int(st.get("next_ticket") or 1)
        for q in qs:
            same = next((x for x in tks
                         if str(x.get("statement")) == str(q["q"])), None)
            if same is not None:
                if q.get("recommend"):
                    same["recommend"] = q["recommend"]
                continue
            t = {"id": f"Q-{next_no}", "statement": str(q["q"]),
                 "recommend": str(q.get("recommend") or ""),
                 "blocked_by": [str(x) for x in (q.get("blocked_by") or [])],
                 "status": "open", "resolution": "", "round": round_no,
                 "ts": round(time.time(), 3)}
            tks.append(t)
            created.append(t)
            next_no += 1
        # C5 机械校验：blocked_by 悬挂引用（含同轮新建票据——以当前 open 集为准）
        known_ids = {str(x.get("id")) for x in tks}
        for t in created:
            for ref in t.get("blocked_by") or []:
                if str(ref) not in known_ids:
                    drift_new.append({
                        "round": round_no, "kind": "dangling-blocked-by",
                        "id": str(ref),
                        "detail": f"票据 {t['id']} 的依赖 {ref} 不存在",
                        "ts": round(time.time(), 3)})
        patch = {"session": self._conv_name(), "round": round_no,
                 "decision_tickets": tks, "next_ticket": next_no,
                 "branch_head": head,
                 "questions": [{"q": str(x.get("statement") or ""),
                                "recommend": str(x.get("recommend") or "")}
                               for x in tks]}
        if drift_new:
            patch["drift"] = design_state.merge_drift(st.get("drift"),
                                                       drift_new)
        if facts:
            merged = list(st.get("facts") or [])
            for f in facts:
                if f not in merged:
                    merged.append(f)
            patch["facts"] = merged
        if is_usable(self.workdir):
            patch["phase"] = "map"
            patch["map_path"] = "WUXING.md"
            patch["map_hash"] = file_hash(map_path(self.workdir))
        else:
            patch["phase"] = "grilling" if (qs or round_no > 1) else "recon"
        state = design_state.save(self.workdir, patch)
        new_phase = str(state.get("phase") or "")
        new_hash = file_hash(map_path(self.workdir))
        # 批 4：【票据】块 → proposed（仅规格就绪——防越序；重复标题不造票）
        created_tickets: list[dict] = []
        if str(state.get("spec_slug") or ""):
            proposals = design_state.parse_tickets(reply)
            if proposals:
                from wuxing import tickets as _tickets
                for p in proposals:
                    current = _tickets.load(self.workdir)
                    if any(t.get("title") == p["title"]
                           and t.get("status") in ("proposed", "ready",
                                                   "running", "done")
                           for t in current):
                        continue
                    try:
                        created_tickets.append(_tickets.create(
                            self.workdir, title=p["title"], goal=p["goal"],
                            acceptance=p["acceptance"], deps=p["deps"],
                            spec=str(state.get("spec_slug") or "")))
                    except ValueError:
                        continue  # 依赖未知（提议顺序问题）——软处理不阻断
        if on_event is not None:
            from wuxing.events import (
                DecisionTicketChanged,
                DesignPhaseChanged,
                ImplTicketChanged,
                MapWritten,
                NeedsDesign,
                SpecWritten,
                TaskDone,
            )
            if new_phase != old_phase:
                on_event(DesignPhaseChanged(session=self._conv_name(),
                                            from_phase=old_phase,
                                            to_phase=new_phase,
                                            round=round_no))
            if new_hash and new_hash != old_hash:
                on_event(MapWritten(path="WUXING.md", hash=new_hash))
            new_spec = str(state.get("spec_slug") or "")
            if new_spec and new_spec != old_spec:
                on_event(SpecWritten(path=str(state.get("spec_path") or ""),
                                     slug=new_spec,
                                     hash=str(state.get("spec_hash") or "")))
            for t in created_tickets:
                on_event(ImplTicketChanged(id=str(t["id"]), status="proposed",
                                           spec=str(t.get("spec") or "")))
            for tid, text in closed:
                on_event(DecisionTicketChanged(session=self._conv_name(),
                                               id=tid, status="closed",
                                               statement=text))
            for t in created:
                on_event(DecisionTicketChanged(session=self._conv_name(),
                                               id=str(t["id"]), status="open",
                                               statement=str(t["statement"])))
            on_event(NeedsDesign(phase=str(state.get("phase") or ""),
                                 round=int(state.get("round") or 0),
                                 questions=list(qs),
                                 map_path="WUXING.md",
                                 map_hash=str(state.get("map_hash") or ""),
                                 reason="map_missing"))
            on_event(TaskDone(status="needs_design"))
        metrics = self._collect_metrics(units, snap)
        report = (f"[循迹设计会话 · 第 {state.get('round')} 轮 · "
                  f"阶段 {state.get('phase')}]\n"
                  + (reply or "（本轮无文本输出）"))
        if qs:
            report += f"\n\n待回答问题 {len(qs)} 个（见设计卡片）"
        return TaskResult(task_text=task_text, fragments=[frag], units=units,
                          artifacts=result_artifacts(units),
                          status="needs_design", report=report,
                          metrics=metrics)
