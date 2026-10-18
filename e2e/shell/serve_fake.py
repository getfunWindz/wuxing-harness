"""假引擎冒烟服务（T6.1 SSE 通用通道浏览器验证）——无 LLM、无真实引擎。

用法：python e2e/shell/serve_fake.py [port]
"""
import json
import os
import pathlib
import sys
import time
from typing import ClassVar

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from wuxing.shell.web.api import register_api
from wuxing.shell.web.hub import EventHub
from wuxing.shell.web.manager import EngineManager
from wuxing.shell.web.server import ShellServer


class UnitStarted:
    def __init__(self, unit_id, domain_id):
        self.unit_id, self.domain_id = unit_id, domain_id


class UnitDone:
    def __init__(self, unit_id, domain_id, status, failure_class=""):
        self.unit_id, self.domain_id, self.status = unit_id, domain_id, status
        self.failure_class = failure_class


class UnitAutoRetry:
    """S1-A：自动恢复事件夹具（类名需与真实事件一致——manager 按类名映射）。"""
    def __init__(self, unit_id, domain_id, kind="retry", attempt=1,
                 candidate=0, model=""):
        self.unit_id, self.domain_id = unit_id, domain_id
        self.kind, self.attempt = kind, attempt
        self.candidate, self.model = candidate, model


class UnitNeedsConfirm:
    def __init__(self, unit_id, domain_id, reason="", impact=None, view=None):
        self.unit_id, self.domain_id, self.reason = unit_id, domain_id, reason
        self.impact = impact or {}
        self.view = view or {}


class UnitReasoning:
    def __init__(self, unit_id, domain_id, round=1, text=""):
        self.unit_id, self.domain_id = unit_id, domain_id
        self.round, self.text = round, text


class ArtifactWritten:
    def __init__(self, unit_id, path, kind=""):
        self.unit_id, self.path, self.kind = unit_id, path, kind


class UnitNeedsAnswer:
    def __init__(self, unit_id, domain_id, question_id, questions=None):
        self.unit_id, self.domain_id = unit_id, domain_id
        self.question_id = question_id
        self.questions = questions or []


class QuestionAnswered:
    def __init__(self, unit_id, question_id, answer, source="text"):
        self.unit_id, self.question_id = unit_id, question_id
        self.answer, self.source = answer, source


class SafetyBlocked:
    def __init__(self, unit_id, domain_id, tool="", command="", reason=""):
        self.unit_id, self.domain_id = unit_id, domain_id
        self.tool, self.command, self.reason = tool, command, reason


class FscAudit:
    def __init__(self, unit_id, domain_id, ratio=0.0):
        self.unit_id, self.domain_id, self.ratio = unit_id, domain_id, ratio


class FscSwitch:
    def __init__(self, unit_id, domain_id, ratio=0.0):
        self.unit_id, self.domain_id, self.ratio = unit_id, domain_id, ratio


class NeedsDesign:
    """批 3：循迹设计信号（类名需与真实事件一致——manager 按类名映射）。"""
    def __init__(self, phase="", round=0, questions=None, map_path="",
                 map_hash="", reason=""):
        self.phase, self.round = phase, round
        self.questions = questions or []
        self.map_path, self.map_hash, self.reason = map_path, map_hash, reason


class MapWritten:
    """批 2：地图写入事件（类名对齐——manager 按类名映射）。"""
    def __init__(self, path="", hash=""):
        self.path, self.hash = path, hash


class DecisionTicketChanged:
    """批 2：决策票据事件（类名对齐）。"""
    def __init__(self, session="", id="", status="", statement=""):
        self.session, self.id = session, id
        self.status, self.statement = status, statement


class SpecWritten:
    """批 3：规格写入事件（类名对齐）。"""
    def __init__(self, path="", slug="", hash=""):
        self.path, self.slug, self.hash = path, slug, hash


class ImplTicketChanged:
    """批 4：实施票据事件（类名对齐）。"""
    def __init__(self, id="", status="", spec=""):
        self.id, self.status, self.spec = id, status, spec


class TaskCancelled:
    pass


class TaskDone:
    def __init__(self, status):
        self.status = status


_SAMPLE_METRICS = {
    "llm_calls": 3,
    "usage": {"input": 1200, "output": 300, "cache_read": 900,
              "cache_write": 120},
    "cache": {"reply": {"hits": 2, "misses": 1, "similar_hits": 1},
              "shape": {"hits": 1, "misses": 0}},
    "breakdown": {"semantic_hits": 1, "semantic_ok": 1,
                  "first_round_misses": 2, "later_round_misses": 1},
    "cost": {"estimate": 0.0123, "save_tokens": 900, "save_cost": 0.0056,
             "cache_read_ratio": 0.75},
    "fsc": {"reused": 2, "sessions": 1, "coverage": 0.5,
            "audited": 0, "switched": 0},
}


class _Artifact:
    def __init__(self, path, kind):
        self.path, self.kind = path, kind


_DEFAULT_ARTIFACTS = [_Artifact("artifacts/报告.md", "md")]


class _Result:
    def __init__(self, status="done", report="mock 报告", artifacts=None,
                 metrics=None):
        self.status = status
        self.report = report
        self.artifacts = artifacts if artifacts is not None else list(_DEFAULT_ARTIFACTS)
        self.metrics = metrics if metrics is not None else _SAMPLE_METRICS


_DEFAULT_SKILLS = {
    "find-skill": {
        "description": "内置技能：检索与发现",
        "level": "builtin",
        "builtin": True,
        "enabled": True,
        # A14：依赖工具声明展示夹具（含一个不在白名单的示例）
        "allowed_tools": ["read_file", "bash"],
        "allowed_tools_missing": ["nonexistent_tool"],
        "content": "---\nname: find-skill\ndescription: 内置技能\n---\n\n检索与发现。\n",
    },
}
# M5 技能管理夹具：模块级存储（跨引擎重载存活；启动重置）——绝不触真实 ~/.wuxing/skills
_SKILLS: dict = dict(_DEFAULT_SKILLS)

# E2-UI 夹具：扩展命令（命令面板 / 逐字段参数表单 / 结果卡片）
_E2_COMMANDS = [
    {"name": "echo", "description": "回声（无参数）", "source": "e2e-ext",
     "args": []},
    {"name": "sum", "description": "求和", "source": "e2e-ext",
     "args": [
         {"name": "a", "label": "加数 A", "type": "int",
          "required": True, "default": None},
         {"name": "b", "label": "加数 B", "type": "int",
          "required": False, "default": 1},
     ]},
]


class FakeEngine:
    _UNIT_DOMAIN: ClassVar[dict] = {"C-1": "execute", "C-2": "verify", "FU-1": "execute"}

    def __init__(self, workdir, auto_confirm=False):
        # manager 传入的可能是 str（历史 500 根因：委托机械实现需 Path 运算）
        self.workdir = pathlib.Path(workdir)
        self.auto_confirm = auto_confirm
        self.fail_confirm = False          # M3：确认失败场景（一次性）
        self.pending_units: set[str] = set()
        self.cancelled = False             # M7：停止任务夹具标志

    # E2-UI：扩展命令（服务端机制校验/转换与真实引擎同口径）
    def list_commands(self):
        return [dict(c) for c in _E2_COMMANDS]

    def run_command(self, name, args=None):
        from wuxing.extensions import coerce_command_args
        cmd = next((c for c in _E2_COMMANDS if c["name"] == name), None)
        if cmd is None:
            raise KeyError(f"未知扩展命令：{name}")
        values, err = coerce_command_args(cmd["args"], args or {})
        if err:
            return {"status": "error", "text": "", "error": err}
        if name == "echo":
            return {"status": "ok", "text": "echo-ok", "error": ""}
        return {"status": "ok",
                "text": f"sum={values.get('a') + values.get('b')}",
                "error": ""}

    @property
    def cfg(self):
        """批 1：模式/预算端点读取的配置面——真实 config_loader 三层合并
        （设置中心写入沙盒 user config 即生效；无键 → 默认）。"""
        from types import SimpleNamespace
        data = {}
        try:
            from wuxing.config_loader import load_config
            data = load_config(self.workdir)
        except Exception:
            data = {}
        return SimpleNamespace(
            mode_default=str(data.get("mode_default") or "minimal-standard"),
            mode_picker_enabled=bool(data.get("mode_picker_enabled", True)),
            context_budget_tokens=int(data.get("context_budget_tokens") or 0),
        )

    def _log_references(self, references):
        """M6 参考文件事实：提交携带的 references 落盘（E2E 双证）。"""
        if not references:
            return
        log_path = pathlib.Path(self.workdir) / "references_log.json"
        entries = []
        if log_path.is_file():
            try:
                entries = json.loads(log_path.read_text(encoding="utf-8"))
            except ValueError:
                entries = []
        entries.append([str(p) for p in references])
        log_path.write_text(json.dumps(entries, ensure_ascii=False),
                            encoding="utf-8")

    def start_session(self, conversation_path=None):
        """修复①（2026-09-20）：manager 经引擎公开 API 建会话——夹具用真实实现。"""
        from wuxing.conversation import ConversationState
        from wuxing.session_api import ConversationSession
        return ConversationSession(self, ConversationState(conversation_path))

    def branch_conversation(self, *args, **kwargs):
        """G1 分支 E2E：委托真实机械实现（无 LLM——summary=llm 经 _llm_is_mock 降级）。"""
        from wuxing.engine import Engine as _RealEngine
        return _RealEngine.branch_conversation(self, *args, **kwargs)

    def _llm_is_mock(self) -> bool:
        """夹具无真 LLM：分支 LLM 摘要一律降级机械（对齐真实 mock 路径）。"""
        return True

    def preview_session_context(self, conversation_path=None, unit_id=None):
        """B 期（2026-09-22）：上下文投影——委托真实引擎模块（夹具不复制投影实现）。

        批 2：窗口/档位阈值读真实配置（设置中心/ API 写入即生效——E2E 可配可验）。"""
        from types import SimpleNamespace

        from wuxing import context_preview
        data = {}
        try:
            from wuxing.config_loader import load_config
            data = load_config(self.workdir)
        except Exception:
            data = {}
        cfg = SimpleNamespace(
            llm="mock", model_context_windows={},
            default_context_window=int(data.get("default_context_window") or 200000),
            conversation_max_chars=int(data.get("conversation_max_chars") or 10000),
            fsc_enabled=True, fsc_fallback_digest=True,
            context_golden_pct=float(data.get("context_golden_pct") or 0.2),
            context_managed_pct=float(data.get("context_managed_pct") or 0.5))
        adapter = SimpleNamespace(workdir=self.workdir, cfg=cfg, skills=None)
        if unit_id:
            return context_preview.preview_unit(adapter, str(unit_id))
        return context_preview.preview_conversation(adapter, conversation_path)

    def run_task(self, text, on_event=None, references=None, conversation=None,
                 overrides=None):
        self._log_references(references)
        # G8-M3 E2E：慢任务（并行准入 / 同会话 409 的确定时间窗）
        if "慢任务" in str(text):
            if on_event:
                on_event(UnitStarted("S-1", "execute"))
            for _ in range(15):
                if self.cancelled:
                    break
                time.sleep(1)
            _st = "cancelled" if self.cancelled else "done"
            if on_event:
                on_event(UnitDone("S-1", "execute", "cancelled" if self.cancelled else "ok"))
                on_event(TaskDone(status=_st))
            return _Result(status=_st, report="[慢任务] 完成")
        # E3-1/R5（T5）：隔离运行 E2E —— 交付物写给当前 workdir
        # （隔离档下 workdir=worktree；主检出不受影响——Apply 后才落地）
        if "隔离演示" in str(text):
            doc = self.workdir / "isolated-report.md"
            doc.write_text("# 隔离产物\n\n- 由隔离 run 写出\n", encoding="utf-8")
            if on_event:
                on_event(UnitStarted("I-1", "execute"))
                on_event(UnitDone("I-1", "execute", "ok"))
                on_event(TaskDone(status="done"))
            return _Result(status="done", report="[隔离演示] 完成")
        # A 期（2026-09-22）：来源开关注入模拟——写 unit_started 实测段长
        # （供 E2E trace 双证；真实装配由 pytest 覆盖）
        try:
            from wuxing.context_sources import resolve as _resolve_sources
            conv_name = getattr(getattr(conversation, "path", None), "name", "")
            src = _resolve_sources(self.workdir, conversation=conv_name)
            hist = digest = 0
            if conversation is not None:
                if src["history"]:
                    hist = len(conversation.context_text(4000))
                if src["digest"]:
                    digest = len((conversation.prev_digest() or "")[:2000])
            row = {"ts": time.time(), "event": "unit_started",
                   "unit_id": "F-1", "domain": "execute",
                   "conversation_round": getattr(conversation, "round_no", 0),
                   "system_chars": 3200, "skills_chars": 0,
                   "history_chars": hist, "digest_chars": digest,
                   "continue_chars": 0}
            # 批 1（2026-09-23）：模式感知 trace——真实 sidecar 解析 + 装配面证据
            # （UI→sidecar→引擎解析链路；真实装配由 pytest 覆盖）
            from wuxing.config import EngineConfig
            from wuxing.session_modes import resolve as _resolve_modes
            mode = _resolve_modes(self.workdir, conversation=conv_name,
                                  default=self.cfg.mode_default)
            pure = mode["mode"] == "minimal" and mode["variant"] == "pure"
            core = list(EngineConfig().minimal_pure_tools)
            full = ["write_artifact", "write_file", "read_dependency",
                    "read_file", "bash", "load_skill", "delegate"]
            row.update({"mode": mode["mode"], "variant": mode["variant"],
                        "conversation": conv_name,
                        "skills_chars": 0 if pure else 120,
                        "tools": core if pure else full})
            tp = pathlib.Path(self.workdir) / ".wuxing" / "trace.jsonl"
            tp.parent.mkdir(parents=True, exist_ok=True)
            with tp.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        except Exception:
            pass
        # M3 确认门 / M6 引擎失败夹具：按任务文本分支（与默认流互斥）
        # ——批 3（2026-09-24）：循迹设计分支（真实 design_state/map_doc 模块）——
        try:
            from wuxing.map_doc import is_usable as _map_usable
            from wuxing.session_modes import resolve as _resolve_modes
            _conv = ""
            try:
                _conv = conversation.path.name if conversation is not None else ""
            except AttributeError:
                _conv = ""
            _mode = _resolve_modes(self.workdir, conversation=_conv)
            if (_mode["mode"] == "theroad" and _map_usable(self.workdir)
                    and "执行票据" in text):
                from wuxing import tickets as _tk2
                _active = [t for t in _tk2.load(self.workdir)
                           if t.get("status") in ("ready", "running")]
                if _active:
                    for _t in _active:
                        _tk2.update(self.workdir, _t["id"],
                                    {"status": "running"})
                        _u = f"F-T{str(_t['id'])[2:]}"
                        if on_event:
                            on_event(UnitStarted(_u, "execute"))
                            on_event(UnitDone(_u, "execute", "ok"))
                            on_event(UnitStarted(f"{_u}-v", "verify"))
                            on_event(UnitDone(f"{_u}-v", "verify", "ok"))
                        _tk2.update(self.workdir, _t["id"],
                                    {"status": "done",
                                     "fragment_ids": [_u, f"{_u}-v"]})
                        if on_event:
                            on_event(ImplTicketChanged(id=_t["id"],
                                                       status="done",
                                                       spec=""))
                    if on_event:
                        on_event(TaskDone(status="done"))
                    return _Result(status="done",
                                   report="[票据编排] 票据执行完成")
            if _mode["mode"] == "theroad" and not _map_usable(self.workdir):
                from wuxing import design_state as _ds
                if "提票据" in text:
                    from wuxing import tickets as _tk
                    _c = []
                    if not any(t.get("title") == "切片一"
                               for t in _tk.load(self.workdir)):
                        _c.append(_tk.create(
                            self.workdir, title=["切片一", "目标：A", "验收：A 可用"][0],
                            goal="A", acceptance=["A 可用"], spec="demo"))
                        _c.append(_tk.create(self.workdir, title="切片二",
                                             goal="B", acceptance=["B 可用"],
                                             deps=["T-1"], spec="demo"))
                    if on_event:
                        on_event(UnitStarted("D-4", "design"))
                        on_event(UnitDone("D-4", "design", "ok"))
                        for _t in _c:
                            on_event(ImplTicketChanged(id=_t["id"],
                                                       status="proposed",
                                                       spec="demo"))
                        on_event(NeedsDesign(phase="map", round=2, questions=[],
                                             map_path="WUXING.md",
                                             reason="tickets_proposed"))
                        on_event(TaskDone(status="needs_design"))
                    return _Result(status="needs_design",
                                   report="[循迹设计会话] 已提议实施票据")
                if "写规格" in text:
                    from wuxing import spec_doc as _sd
                    _e = _sd.write(
                        self.workdir, title="演示规格",
                        sections={"problem": "现状缺失", "solution": "新增 CLI",
                                  "stories": "- 导出报告", "decisions": "选 A",
                                  "testing": "单测 + E2E",
                                  "out_of_scope": "移动端", "notes": "后续"})
                    _ds.save(self.workdir, {
                        "spec_path": f".wuxing/specs/{_e['slug']}.md",
                        "spec_slug": _e["slug"], "spec_hash": _e["hash"]})
                    if on_event:
                        on_event(UnitStarted("D-3", "design"))
                        on_event(UnitDone("D-3", "design", "ok"))
                        on_event(SpecWritten(
                            path=f".wuxing/specs/{_e['slug']}.md",
                            slug=_e["slug"], hash=_e["hash"]))
                        on_event(NeedsDesign(phase="map", round=2, questions=[],
                                             map_path="WUXING.md",
                                             reason="spec_written"))
                        on_event(TaskDone(status="needs_design"))
                    return _Result(status="needs_design",
                                   report="[循迹设计会话] 规格已写入")
                if "写地图" in text:
                    from wuxing import map_doc as _md
                    _md.write_sections(
                        self.workdir, project="演示项目",
                        destination="完成发布工具 v1",
                        route="- [ ] 实现核心\n- [ ] 验证发布",
                        decisions="2026-09-24 · 选 A 方案 · 简单可靠 · 设计会话",
                        fog="部署方式未定", out_of_scope="移动端不做")
                    _ds.save(self.workdir, {
                        "session": _conv, "round": 1, "phase": "map",
                        "questions": [], "facts": ["仅 docs/ 目录"],
                        "map_path": "WUXING.md",
                        "map_hash": _md.file_hash(_md.map_path(self.workdir))})
                    if on_event:
                        on_event(UnitStarted("D-1", "design"))
                        on_event(UnitDone("D-1", "design", "ok"))
                        on_event(NeedsDesign(phase="map", round=1, questions=[],
                                             map_path="WUXING.md",
                                             map_hash=_ds.load(self.workdir).get("map_hash", ""),
                                             reason="map_written"))
                        on_event(TaskDone(status="needs_design"))
                    return _Result(status="needs_design",
                                   report="[循迹设计会话] 地图已写入 WUXING.md")
                _reply = ("已侦察工作区。\n【事实】\n- 仅 docs/ 目录\n"
                          "【问题】\n1. 目标平台？（推荐：Windows 桌面）\n"
                          "2. 是否需要离线？（推荐：需要）\n")
                _qs = _ds.parse_questions(_reply)
                if "回答" in text or "采纳" in text:
                    # 批 2：票据关闭 → 决策入地图（真实 map_doc 口径回放）
                    from wuxing import map_doc as _md2
                    _st0 = _ds.load(self.workdir)
                    _head = str(_st0.get("branch_head") or "")
                    _entry = _md2.append_decision(
                        self.workdir, text="采用 Windows 桌面（夹具回放）",
                        why="用户回答", upstream=_head or "", source="Q-1")
                    _tks = [t for t in _ds.tickets(_st0)
                            if str(t.get("id")) != "Q-1"]
                    _ds.save(self.workdir, {
                        "session": _conv, "round": 2,
                        "decision_tickets": _tks, "next_ticket": 3,
                        "branch_head": _entry["id"], "questions": []})
                    if on_event:
                        on_event(UnitStarted("D-2", "design"))
                        on_event(UnitDone("D-2", "design", "ok"))
                        on_event(DecisionTicketChanged(
                            session=_conv, id="Q-1", status="closed",
                            statement=_entry["text"]))
                        on_event(MapWritten(
                            path="WUXING.md",
                            hash=_md2.file_hash(_md2.map_path(self.workdir))))
                        on_event(NeedsDesign(phase="grilling", round=2,
                                             questions=[],
                                             map_path="WUXING.md",
                                             reason="ticket_closed"))
                        on_event(TaskDone(status="needs_design"))
                    return _Result(status="needs_design",
                                   report="[循迹设计会话] 决策已入地图（D-1）")
                _tks = [{"id": f"Q-{i + 1}", "statement": q["q"],
                         "recommend": q.get("recommend") or "",
                         "blocked_by": list(q.get("blocked_by") or []),
                         "status": "open", "resolution": "", "round": 1,
                         "ts": time.time()}
                        for i, q in enumerate(_qs)]
                _ds.save(self.workdir, {
                    "session": _conv, "round": 1, "phase": "grilling",
                    "questions": _qs, "decision_tickets": _tks,
                    "next_ticket": len(_tks) + 1,
                    "facts": _ds.parse_facts(_reply)})
                if on_event:
                    on_event(UnitStarted("D-1", "design"))
                    on_event(UnitDone("D-1", "design", "ok"))
                    for _t in _tks:
                        on_event(DecisionTicketChanged(
                            session=_conv, id=_t["id"], status="open",
                            statement=_t["statement"]))
                    on_event(NeedsDesign(phase="grilling", round=1,
                                         questions=_qs, map_path="WUXING.md",
                                         reason="map_missing"))
                    on_event(TaskDone(status="needs_design"))
                return _Result(status="needs_design",
                               report="[循迹设计会话] 拷问轮（票据 2 个）")
        except Exception as _wf_e:
            import traceback as _wf_tb
            print("WF-DESIGN-ERR", repr(_wf_e), flush=True)
            _wf_tb.print_exc()
        if "失败分类演示" in text:
            # S1-C 夹具：provider 失败→自动重试→成功（自动重试痕迹）；
            # 预算耗尽失败（分类标签；不出现「建议重跑」）
            if on_event:
                on_event(UnitStarted("F-1", "execute"))
                on_event(UnitDone("F-1", "execute", "failed",
                                  failure_class="provider"))
                on_event(UnitAutoRetry("F-1", "execute", kind="retry",
                                       attempt=1, candidate=0, model="flaky"))
                on_event(UnitDone("F-1", "execute", "ok"))
                on_event(UnitStarted("F-2", "execute"))
                on_event(UnitDone("F-2", "execute", "failed",
                                  failure_class="budget"))
                on_event(TaskDone(status="partial"))
            return _Result(status="partial", report="[失败分类演示] 完成")
        if "引擎失败" in text:
            raise RuntimeError("模拟引擎失败")
        if "思考演示" in text:
            # 修复②（F2）夹具：思维链运行展开/完成折叠观测窗口（≈2.5s）
            if on_event:
                on_event(UnitStarted("T-1", "execute"))
                on_event(UnitReasoning("T-1", "execute", 1,
                                       "先读需求，再拆步骤；核对边界后给结论。"))
            for _ in range(25):
                time.sleep(0.1)
            if on_event:
                on_event(UnitDone("T-1", "execute", "ok"))
                on_event(TaskDone("done"))
            return _Result(report="思考演示完成")
        if "宽DAG" in text:
            # 批次 2（Task 2.5）夹具：并行碎片 chips 观测窗口（≥2 个 running 同时存在）
            if on_event:
                on_event(UnitStarted("W-1", "execute"))
                on_event(UnitStarted("W-2", "plan"))
                on_event(UnitReasoning("W-1", "execute", 1, "并行分支一：撰写报告草稿。"))
                on_event(UnitReasoning("W-2", "plan", 1, "并行分支二：核对方案边界。"))
            for _ in range(20):
                time.sleep(0.1)
            if on_event:
                on_event(UnitDone("W-1", "execute", "ok"))
                on_event(UnitDone("W-2", "plan", "ok"))
                on_event(TaskDone("done"))
            return _Result(report="宽 DAG 演示完成")
        if "慢任务" in text:
            # M7 停止任务夹具：可取消的慢执行（轮询标志 ≤30s——消除提交/点击耗时竞态）
            for _ in range(300):
                if self.cancelled:
                    break
                time.sleep(0.1)
            if self.cancelled:
                self.cancelled = False
                if on_event:
                    on_event(TaskCancelled())
                return _Result(status="cancelled", report="已取消")
            if on_event:
                on_event(UnitDone("S-1", "execute", "ok"))
                on_event(TaskDone("done"))
            return _Result(report="慢任务完成")
        if "确认失败" in text:
            self.fail_confirm = True
            self.pending_units = {"FU-1"}
            if on_event:
                on_event(UnitNeedsConfirm(
                    "FU-1", "execute", "关键碎片待确认",
                    impact={"tools": ["write_artifact", "bash"],
                            "deliverables": ["变更说明"], "depends": [],
                            "summary": "生成变更说明"}))
                on_event(TaskDone("pending"))
            return _Result(status="pending", report="等待确认")
        if "待确认" in text:
            self.pending_units = {"C-1", "C-2"}
            if on_event:
                on_event(UnitNeedsConfirm(
                    "C-1", "execute", "关键碎片待确认",
                    impact={"tools": ["write_artifact", "bash"],
                            "deliverables": ["统计脚本"], "depends": [],
                            "summary": "生成统计脚本"}))
                on_event(UnitNeedsConfirm(
                    "C-2", "verify", "验收需人工确认",
                    impact={"tools": ["read_file"],
                            "deliverables": ["验收结论"], "depends": ["C-1"],
                            "summary": "核验产物"}))
                on_event(TaskDone("pending"))
            return _Result(status="pending", report="等待确认")
        if "确认文案演示" in text:
            # 重大优化清单 #2：四要素渲染 E2E 夹具（V-1 带 view / V-2 旧载荷回退）
            from wuxing import confirm_copy
            self.pending_units = {"V-1", "V-2"}
            if on_event:
                _impact = {"tools": ["write_artifact", "bash"],
                           "deliverables": ["演示产物"], "depends": [],
                           "summary": "生成演示产物"}
                on_event(UnitNeedsConfirm(
                    "V-1", "execute", "有一个步骤待确认", impact=_impact,
                    view=confirm_copy.unit_confirm_view(
                        impact=_impact, trigger="domain_policy",
                        index=1, total=2)))
                on_event(UnitNeedsConfirm(   # 旧载荷（无 view）→ 壳回退路径
                    "V-2", "verify", "有一个步骤待确认（回退演示）"))
                on_event(TaskDone("pending"))
            return _Result(status="pending", report="等待确认")
        if "产物预览演示" in text:
            # A6（W1）夹具：Markdown / 大文本（>512KiB）/ 二进制 三类产物——预览点击 E2E 专用
            adir = self.workdir / "artifacts"
            adir.mkdir(parents=True, exist_ok=True)
            (adir / "报告.md").write_text("# 演示产物\n", encoding="utf-8")
            (adir / "大文件.txt").write_text("A" * 600_000, encoding="utf-8")
            (adir / "图片.png").write_bytes(bytes(range(256)) * 64)
            if on_event:
                on_event(UnitStarted("F-1", "execute"))
                on_event(ArtifactWritten("F-1", "artifacts/报告.md", "md"))
                on_event(ArtifactWritten("F-1", "artifacts/大文件.txt", "txt"))
                on_event(ArtifactWritten("F-1", "artifacts/图片.png", "png"))
                on_event(UnitDone("F-1", "execute", "ok"))
                on_event(TaskDone("done"))
            return _Result(artifacts=[
                _Artifact("artifacts/报告.md", "md"),
                _Artifact("artifacts/大文件.txt", "txt"),
                _Artifact("artifacts/图片.png", "png"),
            ])
        if "提问演示" in text:
            # E2-5（A10）夹具：提问挂起（壳问题卡）→ 答复续跑（answer_unit 回执）
            if on_event:
                on_event(UnitStarted("A-1", "execute"))
                on_event(UnitNeedsAnswer(
                    "A-1", "execute", "ask-A-1-1",
                    [{"title": "目标格式？", "options": ["Markdown", "纯文本"],
                      "multi": False},
                     {"title": "是否需要目录？", "options": ["需要", "不需要"],
                      "multi": False}]))
                on_event(TaskDone("pending"))
            return _Result(status="pending", report="等待答复")
        if on_event:
            on_event(UnitStarted("F-1", "execute"))
            time.sleep(0.3)
            on_event(UnitReasoning(
                "F-1", "execute", 1,
                "先查看仓库结构，再生成统计脚本；\n同时校对两处边界。"))
            on_event(ArtifactWritten("F-1", "artifacts/报告.md", "md"))
            on_event(SafetyBlocked("F-1", "execute", "bash", "rm -rf build/",
                                   "危险命令：递归删除目录"))
            on_event(FscAudit("F-1", "execute", 0.63))
            on_event(FscSwitch("F-1", "execute", 0.81))
            on_event(UnitDone("F-1", "execute", "ok"))
            on_event(TaskDone("done"))
        return _Result()

    def cancel_task(self):
        self.cancelled = True
        return True

    def resume_task(self, on_event=None):
        if (pathlib.Path(self.workdir) / "task_state.json").exists():
            # M7 #8（A3）夹具：磁盘挂起状态 → 恢复后确认门重发
            # （不影响既有续跑路径：无 task_state.json 时行为不变）
            self.pending_units = {"R-1"}
            if on_event:
                on_event(UnitNeedsConfirm(
                    "R-1", "execute", "恢复的挂起单元",
                    impact={"tools": ["write_artifact"],
                            "deliverables": ["恢复产物"],
                            "depends": [], "summary": "重启恢复演示"}))
                on_event(TaskDone("pending"))
            return _Result(status="pending", report="恢复等待确认")
        if on_event:
            on_event(UnitStarted("F-2", "execute"))
            on_event(UnitDone("F-2", "execute", "ok"))
            on_event(TaskDone("done"))
        return _Result(report="已续跑")

    def answer_unit(self, unit_id, question_id, answer, source="text",
                    reason="", on_event=None):
        """E2-5（A10）：答复续跑（夹具回执——答案落盘 + 事件 + done 结果）。"""
        log_path = pathlib.Path(self.workdir) / "ask_log.json"
        entries = []
        if log_path.is_file():
            try:
                entries = json.loads(log_path.read_text(encoding="utf-8"))
            except ValueError:
                entries = []
        entries.append({"unit_id": unit_id, "question_id": question_id,
                        "answer": answer, "source": source})
        log_path.write_text(json.dumps(entries, ensure_ascii=False),
                            encoding="utf-8")
        if on_event:
            on_event(QuestionAnswered(unit_id, question_id, answer, source))
            on_event(UnitDone(unit_id, "execute", "ok"))
            on_event(TaskDone("done"))
        return _Result(status="done", report="已答复并完成")

    def confirm_units(self, items, reason="", on_event=None):
        if self.fail_confirm:
            self.fail_confirm = False
            raise RuntimeError("确认处理失败")
        pairs = [(str(u), bool(a)) for u, a in items]
        # M3 双证：确认请求落盘（items/reason 透传可被 E2E 读取）
        log_path = pathlib.Path(self.workdir) / "confirm_log.json"
        entries = []
        if log_path.is_file():
            try:
                entries = json.loads(log_path.read_text(encoding="utf-8"))
            except ValueError:
                entries = []
        entries.append({"items": [[u, a] for u, a in pairs], "reason": reason})
        log_path.write_text(json.dumps(entries, ensure_ascii=False),
                            encoding="utf-8")
        self.pending_units -= {u for u, _ in pairs}
        for unit_id, approve in pairs:
            domain = self._UNIT_DOMAIN.get(unit_id, "execute")
            if on_event:
                if approve:
                    on_event(UnitStarted(unit_id, domain))
                on_event(UnitDone(unit_id, domain,
                                  "ok" if approve else "rejected"))
        status = ("failed" if any(not a for _, a in pairs)
                  else ("pending" if self.pending_units else "done"))
        if on_event:
            on_event(TaskDone(status))
        return _Result(status=status, report=f"确认处理：{len(pairs)} 项")

    def list_skills(self):
        return [
            {"name": name, "description": info["description"],
             "level": info["level"], "enabled": bool(info.get("enabled", True)),
             # E2-1（B5）：调用策略字段（DTO 对拍要求齐备）
             "model_invocable": bool(info.get("model_invocable", True)),
             "user_invocable": bool(info.get("user_invocable", True)),
             # A14：allowed-tools 声明（只声明不授权）
             "allowed_tools": list(info.get("allowed_tools", [])),
             }
            for name, info in sorted(_SKILLS.items())
        ]

    def skill_detail(self, name):
        info = _SKILLS.get(str(name))
        if info is None:
            return None
        return {"name": str(name), "content": info["content"],
                "scripts": {}, "builtin": bool(info["builtin"]),
                "level": info["level"],
                "allowed_tools": list(info.get("allowed_tools", [])),
                "allowed_tools_missing": list(info.get("allowed_tools_missing", []))}

    def install_skill(self, name, description, content, scripts=None):
        nm = str(name).strip()
        if not nm or nm in (".", "..") or "/" in nm or "\\" in nm:
            raise ValueError(f"非法技能名：{name!r}")
        _SKILLS[nm] = {"description": str(description), "level": "user",
                       "builtin": False, "content": str(content)}
        return {"ok": True, "name": nm, "path": f"/sandbox/skills/{nm}"}

    def remove_skill(self, name):
        nm = str(name).strip()
        info = _SKILLS.get(nm)
        if info is None:
            raise ValueError(f"技能不存在：{nm}")
        if info.get("builtin"):
            raise ValueError(f"内置技能不可卸载：{nm}")
        del _SKILLS[nm]
        return {"ok": True, "name": nm}

    def set_skill_enabled(self, name, enabled):
        """M7 #5 夹具：技能启停（内置只读）。"""
        nm = str(name).strip()
        info = _SKILLS.get(nm)
        if info is None:
            raise ValueError(f"技能不存在：{nm}")
        if info.get("builtin"):
            raise ValueError(f"内置技能不可停用：{nm}")
        info["enabled"] = bool(enabled)
        return {"ok": True, "name": nm, "enabled": bool(enabled)}

    def discover_skills(self, goal, constraints="", max_results=5):
        return {"ok": True, "items": [
            {"name": "radar-demo", "description": f"发现候选：{goal}"[:80]},
        ]}

    def mcp_status(self):
        return {"enabled": True, "servers": [{
            "name": "demo-mcp", "command": "npx", "args": ["-y", "demo-mcp"],
            "tools": [{"name": "search", "permissions": {"read": True}}],
            "stats": {"connections": 2, "calls": 17},
        }]}


def _title_stub(path):
    """会话标题桩（无真 LLM——与夹具种子同口径）。

    FAKE_TITLE_DELAY_MS：人为延迟标题响应——UI-1「会话列表先上屏」断言用
    （列表不得被标题生成阻塞）。
    """
    delay_ms = float(os.environ.get("FAKE_TITLE_DELAY_MS", "0") or "0")
    if delay_ms > 0:
        time.sleep(delay_ms / 1000.0)
    name = pathlib.Path(path).name
    if name.startswith("conversation") and "1710000000" in name:
        return "变更摘要会话"
    if name.startswith("conversation") and "1710000100" in name:
        return "并行示例会话"
    return ""


def _seed_fixture2(base2: pathlib.Path) -> None:
    """第二夹具工作区种子（每轮重置；运行时生成——仓库零预置）。

    UI-1/UI-4 断言依赖：fake-ws2 需有一行 round 会话（context-preview 正向控制）。
    """
    import shutil as _sh
    _sh.rmtree(base2 / ".wuxing", ignore_errors=True)
    (base2 / ".wuxing").mkdir(parents=True, exist_ok=True)
    (base2 / "confirm_log.json").unlink(missing_ok=True)
    (base2 / ".wuxing" / "conversation-1710000400.jsonl").write_text(
        json.dumps({"round": 1, "user_text": "第二工作区示例任务",
                    "summary": "done", "artifacts": [], "ts": 1710000400.0},
                   ensure_ascii=False) + "\n", encoding="utf-8")


def main():
    base = pathlib.Path(__file__).resolve().parent / "fake-ws"
    base.mkdir(exist_ok=True)
    _SKILLS.clear()
    _SKILLS.update(_DEFAULT_SKILLS)  # M5 技能管理夹具：每轮重置
    base2 = pathlib.Path(__file__).resolve().parent / "fake-ws2"
    _seed_fixture2(base2)
    (base / "ws.json").unlink(missing_ok=True)  # 每轮同一初始状态（工作区/文件夹）
    (base / "confirm_log.json").unlink(missing_ok=True)  # M3 确认日志（每轮重置）
    (base / "brain_memory.json").unlink(missing_ok=True)  # M4 智脑空态（每轮重置）
    (base / "references_log.json").unlink(missing_ok=True)  # M6 参考文件事实（每轮重置）
    (base / "events.jsonl").unlink(missing_ok=True)  # 事件日志（每轮重置——seq 单调、无跨轮残留）
    (base / "events.jsonl.1").unlink(missing_ok=True)
    (base / ".wuxing" / "context-edits.jsonl").unlink(missing_ok=True)  # B 期：编辑 sidecar 每轮重置
    (base / ".wuxing" / "context-sources.json").unlink(missing_ok=True)  # A 期：来源开关每轮重置
    (base / ".wuxing" / "session-modes.json").unlink(missing_ok=True)  # 批 1：模式 sidecar 每轮重置
    (base / "WUXING.md").unlink(missing_ok=True)  # 批 3：工作区地图每轮重置（根目录——防跨轮污染）
    artifacts_dir = base / "artifacts"
    artifacts_dir.mkdir(exist_ok=True)
    (artifacts_dir / "报告.md").write_text("# 演示产物\n", encoding="utf-8")
    import shutil as _shutil
    _shutil.rmtree(base / ".wuxing", ignore_errors=True)   # 会话文件也重置
    (base / ".wuxing").mkdir(exist_ok=True)   # M2 会话种子（conversation*.jsonl）
    # E2-UI：装配预设夹具（工作区级 + 损坏预设展示「损坏」可见性）
    presets_dir = base / ".wuxing" / "presets"
    presets_dir.mkdir(parents=True, exist_ok=True)
    (presets_dir / "e2e.jsonc").write_text(
        '{"description": "E2E 演示预设", "tools": ["bash", "read_file"]}\n',
        encoding="utf-8")
    (presets_dir / "broken.jsonc").write_text(
        '{"extends": "nope"}\n', encoding="utf-8")
    (base / ".wuxing" / "conversation-1710000000.jsonl").write_text(
        '{"role":"user","content":"生成一份变更摘要"}\n'
        '{"role":"assistant","content":"已完成。"}\n',
        encoding="utf-8")
    # M4 观测视图种子（溯源/链路/报告）
    (base / ".wuxing" / "provenance.jsonl").write_text(
        json.dumps({"provenance_id": "p1", "unit_id": "P-1", "parent_id": "",
                    "task_hash": "h", "goal": "演示", "domain": "execute",
                    "model": "mock", "status": "ok", "artifacts": [],
                    "ts": 1710000000.0}, ensure_ascii=False) + "\n"
        + json.dumps({"provenance_id": "p2", "unit_id": "P-2", "parent_id": "P-1",
                      "task_hash": "h", "goal": "演示续", "domain": "verify",
                      "model": "mock", "status": "failed", "artifacts": [],
                      "ts": 1710000060.0}, ensure_ascii=False) + "\n",
        encoding="utf-8")
    (base / ".wuxing" / "trace.jsonl").write_text(
        json.dumps({"ts": 1710000000.0, "event": "unit_start",
                    "unit_id": "P-1", "domain": "execute"},
                   ensure_ascii=False) + "\n", encoding="utf-8")
    # ---- 2026-09-21：工作区域轮次化/碎片会话/轨迹种子（线性轮 + 并行轮 + 碎片会话文件）----
    from wuxing.provenance import task_hash as _task_hash
    wux = base / ".wuxing"
    (wux / "conversation-1710000100.jsonl").write_text(
        json.dumps({"round": 1, "user_text": "线性示例任务", "summary": "done",
                    "artifacts": [], "ts": 1710000100.0}, ensure_ascii=False) + "\n"
        + json.dumps({"round": 2, "user_text": "并行示例任务", "summary": "done",
                      "artifacts": [], "ts": 1710000200.0}, ensure_ascii=False) + "\n",
        encoding="utf-8")
    # 批 2（2026-09-24）：黄金期档位——大会话种子（多轮累计：单轮截断 200 字符；
    # 20 轮 × 160 字 ≈ 3400 字 ≈ 6800 估算 token——小窗口下可验 严管/正常 两档）
    _big_turns = "".join(
        json.dumps({"round": i, "user_text": "长文档演示内容。" * 20,
                    "summary": f"第{i}轮小结", "artifacts": [],
                    "ts": 1710000300.0 + i}, ensure_ascii=False) + "\n"
        for i in range(1, 21))
    (wux / "conversation-1710000300.jsonl").write_text(_big_turns,
                                                        encoding="utf-8")
    with (wux / "provenance.jsonl").open("a", encoding="utf-8") as f:
        for row in [
            {"provenance_id": "q1", "unit_id": "L-1", "parent_id": "",
             "task_hash": _task_hash("线性示例任务"), "goal": "线性步骤", "domain": "execute",
             "model": "mock", "status": "ok", "artifacts": ["docs/报告.md"], "ts": 1710000090.0},
            {"provenance_id": "q2", "unit_id": "P-a", "parent_id": "",
             "task_hash": _task_hash("并行示例任务"), "goal": "并行分支A", "domain": "execute",
             "model": "mock", "status": "ok", "artifacts": [], "ts": 1710000150.0},
            {"provenance_id": "q3", "unit_id": "P-b", "parent_id": "",
             "task_hash": _task_hash("并行示例任务"), "goal": "并行分支B", "domain": "plan",
             "model": "mock", "status": "ok", "artifacts": ["docs/方案.md"], "ts": 1710000160.0},
        ]:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    with (wux / "trace.jsonl").open("a", encoding="utf-8") as f:
        for ev in [
            {"ts": 1710000080.0, "event": "unit_started", "unit_id": "L-1", "domain": "execute"},
            {"ts": 1710000090.0, "event": "unit_done", "unit_id": "L-1", "domain": "execute", "status": "ok"},
            {"ts": 1710000140.0, "event": "unit_started", "unit_id": "P-a", "domain": "execute",
             "conversation_round": 2, "system_chars": 3200, "skills_chars": 120},
            {"ts": 1710000145.0, "event": "unit_started", "unit_id": "P-b", "domain": "plan",
             "conversation_round": 2, "system_chars": 2800, "skills_chars": 120},
            {"ts": 1710000154.0, "event": "llm_call", "unit_id": "P-a", "domain": "execute",
             "round": 1, "conversation_round": 2, "input": 5400, "output": 120,
             "cache_read": 3800, "cache_write": 0, "latency_ms": 900},
            {"ts": 1710000155.0, "event": "tool_call", "unit_id": "P-a", "domain": "execute",
             "round": 2, "name": "write_artifact", "status": "ok", "latency_ms": 1},
            {"ts": 1710000156.0, "event": "unit_done", "unit_id": "P-a", "domain": "execute", "status": "ok"},
            {"ts": 1710000175.0, "event": "unit_done", "unit_id": "P-b", "domain": "plan", "status": "ok"},
            {"ts": 1710000176.0, "event": "session_created", "unit_id": "P-a", "domain": "execute",
             "key": "docs", "session_chars": 1527, "reuse": 0},
        ]:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    sess = wux / "sessions"
    sess.mkdir(exist_ok=True)
    (sess / "1-P-a.jsonl").write_text(
        json.dumps({"round": 0, "state": "seed", "status": "", "ts": 1710000140.0,
                    "messages": [{"role": "system", "content": "（夹具）碎片会话系统提示"},
                                 {"role": "user", "content": "并行分支A：产出示例产物"}]},
                   ensure_ascii=False) + "\n"
        + json.dumps({"round": 1, "state": "thinking", "status": "", "ts": 1710000150.0,
                      "messages": [{"role": "user", "content": "（夹具）LLM 输出示例"},
                                   {"role": "user", "content": "[tool] write_artifact: ok"}]},
                     ensure_ascii=False) + "\n"
        + json.dumps({"round": 1, "state": "done", "status": "ok", "ts": 1710000156.0,
                      "messages": []}, ensure_ascii=False) + "\n",
        encoding="utf-8")
    (sess / "1-P-b.jsonl").write_text(
        json.dumps({"round": 0, "state": "seed", "status": "", "ts": 1710000145.0,
                    "messages": [{"role": "system", "content": "（夹具）碎片会话系统提示"},
                                 {"role": "user", "content": "并行分支B：方案产物"}]},
                   ensure_ascii=False) + "\n"
        + json.dumps({"round": 1, "state": "done", "status": "ok", "ts": 1710000175.0,
                      "messages": []}, ensure_ascii=False) + "\n",
        encoding="utf-8")
    docs_dir = base / "docs"
    docs_dir.mkdir(exist_ok=True)
    (docs_dir / "报告.md").write_text("# 演示报告\n\n- 条目一\n", encoding="utf-8")
    static = (pathlib.Path(__file__).resolve().parents[2]
              / "wuxing" / "shell" / "web" / "static")
    # E3-1/R5（T5）：隔离运行 E2E —— 夹具工作区需为 git 仓库（幂等；无 git 则跳过）
    import subprocess as _sp
    try:
        if not (base / ".git").exists():
            _sp.run(["git", "init", "-q", str(base)], check=True,
                    stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
            _sp.run(["git", "-C", str(base), "config", "user.email",
                     "e2e@fixture"], check=True)
            _sp.run(["git", "-C", str(base), "config", "user.name", "e2e"],
                    check=True)
            (base / "fixture-init.txt").write_text("fixture\n",
                                                   encoding="utf-8")
            _sp.run(["git", "-C", str(base), "add", "fixture-init.txt"],
                    check=True)
            _sp.run(["git", "-C", str(base), "commit", "-qm", "fixture-init"],
                    check=True)
        # 残留 worktree 元数据清理（每轮夹具复位）
        _sp.run(["git", "-C", str(base), "worktree", "prune"], check=False,
                stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
    except (OSError, _sp.SubprocessError):
        pass   # 无 git 环境：worktree 套件自会 loud 拒绝（不影响其他套件）
    # P2 设置 E2E：配置/凭据沙盒隔离（绝不触碰真实 ~/.wuxing）+ 供应商种子 + 发现打桩
    import shutil

    import wuxing.config_contract as cc
    import wuxing.config_loader as cl
    import wuxing.credentials as creds
    import wuxing.shell.web.api_routes.providers as providers_mod

    sandbox = base / "user"
    shutil.rmtree(sandbox, ignore_errors=True)
    sandbox.mkdir(parents=True, exist_ok=True)
    cc.user_config_path = lambda: sandbox / "config.jsonc"
    cl._global_config_dir = lambda: sandbox
    creds.credentials_path = lambda: sandbox / "credentials.json"
    (sandbox / "config.jsonc").write_text(json.dumps({
        "providers": {
            "demo-provider": {"type": "deepseek", "display_name": "演示供应商",
                              "base_url": "https://api.deepseek.com"},
        }
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # 批 3：服务重启恢复双证——FAKE_RESTORE 目录（E2E 备份的设计态/地图）覆盖种子
    _restore = os.environ.get("FAKE_RESTORE")
    if _restore and pathlib.Path(_restore).is_dir():
        import shutil as _sh3
        _sh3.copytree(_restore, base, dirs_exist_ok=True)
    providers_mod.discover_models = lambda base_url, ptype, api_key=None, timeout=30.0: [
        {"id": "demo-model-alpha", "display_name": "Demo Alpha"},
        {"id": "demo-model-beta"},
        {"id": "zzz-hidden"},
    ]
    hub = EventHub(journal_path=base / "events.jsonl")
    mgr = EngineManager(hub=hub,
                        engine_factory=lambda wd, ac: FakeEngine(wd, ac),
                        state_path=base / "ws.json")
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    srv = ShellServer(port=port, hub=hub, static_dir=static)

    def _dialog_stub(kind):  # M6 系统对话框桥桩（E2E 不弹真实对话框）
        # 测试旋钮（2026-09-30）：模拟系统对话框阻塞（生产=用户交互期间请求挂起）
        # —— 用于复现/回归「连击 → 双对话框」防重入守卫。默认 0（CI 零行为差异）。
        _delay_ms = float(os.environ.get("WUXING_FAKE_DIALOG_DELAY_MS", "0") or 0)
        if _delay_ms > 0:
            time.sleep(_delay_ms / 1000.0)
        if kind == "directory":   # 新建工作区：选文件夹（2026-09-19）
            picked = (base.parent / ".runtime"
                      / f"picked-ws-{int(time.time() * 1000) % 100000}")
            picked.mkdir(parents=True, exist_ok=True)
            return [str(picked)]
        return [str(base / "docs" / "报告.md")]

    register_api(srv, mgr, dialog_runner=_dialog_stub, title_runner=_title_stub)
    port = srv.start()
    mgr.open_workspace(str(base))
    mgr.open_workspace(str(base2))
    print(f"URL http://127.0.0.60:{port}/", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        srv.stop()


if __name__ == "__main__":
    main()
