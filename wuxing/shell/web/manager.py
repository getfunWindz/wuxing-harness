"""EngineManager（壳 P1 · B3）——工作区注册表 + 任务线程 + 命令路由。

设计 §3：**工作区 = 并发单位**（每工作区一个活动任务；全局并发上限默认 2，
P1 超出即拒绝——排队语义留 P2）；引擎**懒构造**（打开工作区不建引擎）；
引擎事件经桥接器标准化后进入 EventHub（`workspace_id`/`run_id` 标注）；
confirm/resume/cancel 路由到引擎公开 API（run 级）。
"""
import hashlib
import itertools
import json
import logging
import os
import pathlib
import re
import threading
import time
import uuid

from wuxing import worktrees
from wuxing.atomic_write import read_text_retry
from wuxing.shell.web.contracts import ENGINE_EVENT_TYPE_MAP as _EVENT_TYPE
from wuxing.shell.web.hub import EventHub

logger = logging.getLogger(__name__)


class ManagerError(Exception):
    code = "error"


class NotFoundError(ManagerError):
    code = "not_found"


class BusyError(ManagerError):
    code = "busy"


def _snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", str(name)).lower()


def _event_data(e) -> dict:
    """事件对象 → JSON 安全 dict（只保留标量/容器）。"""
    out = {}
    for k, v in vars(e).items():
        if isinstance(v, (str, int, float, bool, list, dict, type(None))):
            out[k] = v
    return out


class _Run:
    __slots__ = ("deferred_terminal", "done", "engine", "error",
                 "isolated", "kind", "overrides", "pending_answers",
                 "pending_confirms",
                 "references",
                 "result", "run_id", "session", "started_at", "status",
                 "submit_seq", "task_text", "thread", "unit", "worktree_path",
                 "ws_id",
                 "ws_path")
    _seq = itertools.count(1)   # 提交序计数（快照同刻 tie-break——E0-2）

    def __init__(self, run_id, ws_id, task_text, references=None, session="",
                 unit="", overrides=None, ws_path="", isolated=False,
                 worktree_path=""):
        self.run_id = run_id
        self.ws_id = ws_id
        # A6-T1：产物 mtime 的 stat 根（工作区绝对路径；空 = 不可得 → 0.0）
        self.ws_path = str(ws_path or "")
        self.task_text = task_text
        self.references = list(references or [])
        self.session = str(session or "")
        # E3-1/R5（T4）：隔离 run——worktree 执行档（终态后保留至 Apply/丢弃）
        self.isolated = bool(isolated)
        self.worktree_path = str(worktree_path or "")
        # 二期批 1：显式闸覆盖集（无地图执行 override——透传引擎）
        self.overrides = list(overrides or []) or None
        # 碎片会话后半程（2026-09-22）：碎片内提交的绑定身份（空 = 主会话提交）
        self.unit = str(unit or "")
        # G8-M2：per-run 引擎（并行 run 不共享实例）与计划类型（design/execution）
        self.engine = None
        self.kind = "execution"
        self.status = "running"
        self.result = None
        self.error = ""
        self.pending_confirms = []
        # E2-5（A10）：待答问题组（unit_needs_answer 事件登记；答复/终态清理）
        self.pending_answers = []
        # 终态事件缓发槽（result 落库后由 _flush_terminal 发出——防快照竞态）
        self.deferred_terminal = None
        self.done = threading.Event()
        self.thread = None
        self.started_at = time.time()
        # E0-2 验收发现（既有 flake）：Windows 计时器粒度下多次提交可同刻——
        # 快照「最近活动 run」需按提交序确定性裁决（started_at 同刻时适用）
        self.submit_seq = next(_Run._seq)

    def _artifact_mtime(self, rel: str) -> float:
        """A6-T1：产物 mtime（工作区内 stat）；缺失/越界/异常 → 0.0（不造假）。"""
        if not rel or not self.ws_path:
            return 0.0
        try:
            root = pathlib.Path(self.ws_path).resolve()
            target = (root / rel).resolve()
            if not target.is_relative_to(root):
                return 0.0
            return float(target.stat().st_mtime)
        except (OSError, ValueError):
            # 文件缺失/权限/路径非法字符等 → 0.0（元数据不可得时诚实缺省）
            return 0.0

    def public(self) -> dict:
        res = None
        if self.result is not None:
            artifacts = [{"path": str(getattr(a, "path", "")),
                          "kind": str(getattr(a, "kind", "")),
                          "mtime": self._artifact_mtime(
                              str(getattr(a, "path", "")))}
                         for a in (getattr(self.result, "artifacts", None)
                                   or [])]
            res = {"status": str(getattr(self.result, "status", "")),
                   "report": str(getattr(self.result, "report", "") or ""),
                   "artifacts": artifacts,
                   "metrics": getattr(self.result, "metrics", None) or {}}
        return {"run_id": self.run_id, "workspace_id": self.ws_id,
                "status": self.status, "error": self.error,
                "task_text": self.task_text[:200],
                "session": self.session,
                "isolated": self.isolated,
                "worktree_path": self.worktree_path,
                "pending_confirms": [dict(p) for p in self.pending_confirms],
                "pending_answers": [dict(p) for p in self.pending_answers],
                "result": res}


class EngineManager:
    """工作区注册表 + 任务线程池（P1：拒绝超限，不排队）。"""

    def __init__(self, hub=None, engine_factory=None, max_concurrent: int = 2,
                 state_path=None, history_path=None,
                 max_parallel_runs_per_ws: int = 3):
        self.hub = hub if hub is not None else EventHub()
        self.max_concurrent = max(1, int(max_concurrent))
        # G8-M2：每工作区并行上限（0/1 = 关闭并行，退回单 run 旧行为）
        self.max_parallel_runs_per_ws = int(max_parallel_runs_per_ws)
        self.state_path = pathlib.Path(state_path) if state_path else None
        if history_path is not None:
            self.history_path = pathlib.Path(history_path)
        elif self.state_path is not None:
            self.history_path = self.state_path.parent / "tasks.jsonl"
        else:
            self.history_path = None
        self._factory = engine_factory or self._default_factory
        self._lock = threading.Lock()
        self._history_lock = threading.Lock()  # 历史文件串行（追加/读取/清除——防并发半读）
        self._ws = {}        # ws_id -> {id, path, name, auto_confirm, status, folder}
        self._folders = []   # [{id, name, collapsed}]（IDE 式收纳，验收迭代 3）
        self._engines = {}   # ws_id -> engine（懒构造）
        self._runs = {}      # run_id -> _Run
        self._active = {}    # ws_id -> set[run_id]（G8-M2：并行 run 集合）
        self._cmd_locks = {}  # ws_id -> Lock（确认/续跑串行）
        self._cmd_guard = threading.Lock()
        self._load_state()

    @staticmethod
    def _default_factory(workdir, auto_confirm, run_id=None,
                         preset_session=None, state_root=None):
        from wuxing.engine import Engine
        return Engine(workdir=pathlib.Path(workdir),
                      state_root=(pathlib.Path(state_root)
                                  if state_root else None),
                      auto_confirm=bool(auto_confirm),
                      run_id=run_id, preset_session=preset_session)

    # ---- 服务侧状态持久化（~/.wuxing/shell/workspaces.json） ----
    def _load_state(self) -> None:
        if not (self.state_path and self.state_path.exists()):
            return
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            for w in data.get("workspaces", []):
                if w.get("id") and w.get("path"):
                    self._ws[w["id"]] = {
                        "id": w["id"], "path": w["path"],
                        "name": w.get("name") or pathlib.Path(w["path"]).name,
                        "auto_confirm": bool(w.get("auto_confirm", False)),
                        "status": "idle",
                        "folder": w.get("folder") or None}
            for f in data.get("folders", []):
                if isinstance(f, dict) and f.get("id") and f.get("name"):
                    self._folders.append({
                        "id": str(f["id"]), "name": str(f["name"]),
                        "collapsed": bool(f.get("collapsed", False))})
        except (OSError, ValueError) as exc:
            logger.debug("壳状态损坏，以空注册表启动：%s", exc)

    def _save_state(self) -> None:
        if not self.state_path:
            return
        payload = {"workspaces": [
            {"id": w["id"], "path": w["path"], "name": w["name"],
             "auto_confirm": w["auto_confirm"], "folder": w.get("folder")}
            for w in list(self._ws.values())],
            "folders": [dict(f) for f in self._folders]}
        tmp = self.state_path.with_suffix(".json.tmp")
        # Windows 文件占用（杀软扫描/并发读）会使 os.replace 偶发失败——重试三次
        for attempt in range(3):
            try:
                self.state_path.parent.mkdir(parents=True, exist_ok=True)
                tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                               encoding="utf-8")
                os.replace(tmp, self.state_path)
                return
            except OSError:
                time.sleep(0.02 * (attempt + 1))
        # 状态持久化是优化不是生命线（重试后仍失败则放弃）

    # ---- 工作区 ----
    def open_workspace(self, path, auto_confirm: bool = False,
                       name: str | None = None) -> dict:
        p = pathlib.Path(path).resolve()
        if not p.is_dir():
            raise NotFoundError(f"目录不存在：{p}")
        ws_id = hashlib.sha256(str(p).encode("utf-8")).hexdigest()[:12]
        with self._lock:
            if ws_id in self._ws:
                if not name:
                    return dict(self._ws[ws_id])
                self._ws[ws_id]["name"] = str(name).strip() or p.name
                result = dict(self._ws[ws_id])
            else:
                entry = {"id": ws_id, "path": str(p),
                         "name": (str(name).strip() if name else "") or p.name,
                         "auto_confirm": bool(auto_confirm), "status": "idle",
                         "folder": None}
                self._ws[ws_id] = entry
                result = dict(entry)
        self._save_state()
        return result

    def close_workspace(self, ws_id: str) -> None:
        with self._lock:
            if ws_id not in self._ws:
                raise NotFoundError(f"未知工作区：{ws_id}")
            if self._active.get(ws_id):
                raise BusyError("工作区有活动任务——先完成或取消")
            self._ws.pop(ws_id, None)
            self._engines.pop(ws_id, None)
        self._save_state()

    def list_workspaces(self) -> list:
        with self._lock:
            return [{"id": w["id"], "path": w["path"], "name": w["name"],
                     "auto_confirm": w["auto_confirm"],
                     "status": w["status"],
                     "folder": w.get("folder")} for w in self._ws.values()]

    # ---- 工作区文件夹（验收迭代 3 · 4b：IDE 式收纳，壳侧状态持久化） ----

    def list_folders(self) -> list:
        with self._lock:
            return [dict(f) for f in self._folders]

    def create_folder(self, name: str) -> dict:
        nm = str(name or "").strip()
        if not nm:
            raise ValueError("文件夹名不能为空")
        folder = {"id": uuid.uuid4().hex[:12], "name": nm, "collapsed": False}
        with self._lock:
            self._folders.append(folder)
        self._save_state()
        return dict(folder)

    def _folder(self, folder_id: str) -> dict | None:
        for f in self._folders:
            if f["id"] == folder_id:
                return f
        return None

    def update_folder(self, folder_id: str, name=None, collapsed=None) -> dict:
        with self._lock:
            f = self._folder(folder_id)
            if f is None:
                raise NotFoundError(f"未知文件夹：{folder_id}")
            if name is not None:
                nm = str(name).strip()
                if not nm:
                    raise ValueError("文件夹名不能为空")
                f["name"] = nm
            if collapsed is not None:
                f["collapsed"] = bool(collapsed)
            out = dict(f)
        self._save_state()
        return out

    def delete_folder(self, folder_id: str) -> dict:
        with self._lock:
            f = self._folder(folder_id)
            if f is None:
                raise NotFoundError(f"未知文件夹：{folder_id}")
            self._folders = [x for x in self._folders if x["id"] != folder_id]
            for w in self._ws.values():
                if w.get("folder") == folder_id:
                    w["folder"] = None
            out = dict(f)
        self._save_state()
        return out

    def set_workspace_folder(self, ws_id: str, folder_id: str | None) -> dict:
        with self._lock:
            w = self._ws.get(ws_id)
            if w is None:
                raise NotFoundError(f"未知工作区：{ws_id}")
            if folder_id is not None and self._folder(folder_id) is None:
                raise NotFoundError(f"未知文件夹：{folder_id}")
            w["folder"] = folder_id or None
            out = {"id": w["id"], "path": w["path"], "name": w["name"],
                   "auto_confirm": w["auto_confirm"], "status": w["status"],
                   "folder": w["folder"]}
        self._save_state()
        return out

    def _workspace(self, ws_id: str) -> dict:
        with self._lock:
            w = self._ws.get(ws_id)
        if w is None:
            raise NotFoundError(f"未知工作区：{ws_id}")
        return w

    def get_workspace(self, ws_id: str) -> dict:
        """公开读取（静态信息——含 path，供产物/会话端点做路径限定）。"""
        return dict(self._workspace(ws_id))

    def _engine_for(self, ws_id: str):
        w = self._workspace(ws_id)
        with self._lock:
            eng = self._engines.get(ws_id)
        if eng is None:
            eng = self._factory(w["path"], w["auto_confirm"])
            with self._lock:
                self._engines[ws_id] = eng
        return eng

    # ---- 任务 ----
    def engine_for(self, ws_id: str):
        """公开取引擎（壳侧只读用途，如会话标题生成——与 _engine_for 同语义）。"""
        return self._engine_for(ws_id)

    def active_sessions(self, ws_id: str) -> set[str]:
        """活动 run 的会话集合（G8-M3：陈旧认领判定）。"""
        with self._lock:
            return {r.session for r in self._runs.values()
                    if r.ws_id == ws_id and r.status == "running" and r.session}

    # ---- G5：装配代际诊断 ----
    def assemblies_summary(self) -> list[dict]:
        """已构造引擎的装配代摘要（壳诊断只读；无装配信息的引擎跳过）。"""
        with self._lock:
            engines = list(self._engines.items())
        out: list[dict] = []
        for ws_id, engine in engines:
            asm = getattr(engine, "assembly", None)
            if not isinstance(asm, dict) or not asm.get("id"):
                continue
            out.append({
                "workspace_id": ws_id,
                "path": str(getattr(engine, "workdir", "")),
                "id": str(asm.get("id")),
                "computed_at": float(asm.get("computed_at") or 0.0),
                "degraded": [
                    {"component": str(d.get("component", "")),
                     "name": str(d.get("name", "")),
                     "reason": str(d.get("reason", ""))}
                    for d in (asm.get("degraded") or [])
                    if isinstance(d, dict)
                ],
            })
        return sorted(out, key=lambda x: x["workspace_id"])

    def submit(self, ws_id: str, task_text: str, references=None,
               session=None, unit=None, override=None,
               claim_override: bool = False,
               isolate_run: bool = False) -> str:
        """提交任务（G8-M2：并行准入 + 提交期票据认领）。

        session 指定则续写该会话，未指定则自动新建会话文件（修复①）。
        unit（碎片会话后半程 2026-09-22）：碎片会话视图内提交时的绑定身份。
        override（二期批 1）：显式闸覆盖（当前仅 "no_map"——无地图执行）。
        isolate_run（E3-1/R5）：显式隔离档——在 git worktree 中执行
        （非 git loud 拒绝；失败拒绝，不静默降级共享执行）。
        准入（Q3=B）：计划类型 design 可并行；执行类每工作区 ≤1（执行槽）；
        每会话同时 1 个活动 run；每工作区并行上限 max_parallel_runs_per_ws
        （≤1 退回旧行为）；全局 max_concurrent 保持。
        认领（Q4=A）：theroad 执行提交先检查意图票据认领冲突（BusyError，
        附持有者）；未认领票据批量原子认领；claim_override=True 强制移交。
        """
        ws = self._workspace(ws_id)
        unit_id = str(unit or "").strip()[:200]
        override_id = str(override or "").strip()
        session_name = self._prepare_session(pathlib.Path(ws["path"]), session)
        from wuxing.engine import (
            session_plan as _session_plan,  # 壳白名单：经 engine 公开面（engine 内部转发 session_plan 模块）
        )
        plan = _session_plan(ws["path"], session_name)
        kind = str(plan.get("kind") or "execution")
        claim_ready = kind == "execution" and str(plan.get("mode")) == "theroad"
        run_id = uuid.uuid4().hex[:12]
        with self._lock:
            act = self._active.get(ws_id) or set()
            cap = self.max_parallel_runs_per_ws
            if cap <= 1 and act:
                raise BusyError("该工作区已有活动任务")
            if cap > 1 and len(act) >= cap:
                raise BusyError("该工作区并行已达上限")
            if any(r.ws_id == ws_id and r.kind == "recovery"
                   and r.status == "running" for r in self._runs.values()):
                raise BusyError("该工作区正在执行恢复——请稍后")
            if any(r.ws_id == ws_id and r.session == session_name
                   and r.status == "running" for r in self._runs.values()):
                raise BusyError("该会话已有活动任务")
            if any(r.ws_id == ws_id and r.session == session_name
                   and r.pending_confirms for r in self._runs.values()):
                raise BusyError("该会话有待确认任务，请先处理确认门")
            total = sum(len(s) for s in self._active.values())
            if total >= self.max_concurrent:
                raise BusyError("全局并发已达上限")
            rec = _Run(run_id, ws_id, str(task_text), references=references,
                       session=session_name, unit=unit_id,
                       overrides=[override_id] if override_id else None,
                       ws_path=ws["path"])
            rec.kind = kind
            self._runs[run_id] = rec
            self._active.setdefault(ws_id, set()).add(run_id)
            self._ws[ws_id]["status"] = "running"
        if isolate_run:
            # E3-1/R5（W1）：显式隔离档——非 git/创建失败 loud 拒绝（不静默降级）
            try:
                wt = worktrees.create(ws["path"], run_id)
                rec.worktree_path = str(wt)
                worktrees.record_run(ws["path"], run_id, wt)
            except worktrees.WorktreeError as exc:
                self._discard_worktree(rec)
                self._rollback_submit(run_id)
                raise ValueError(str(exc)) from exc
            rec.isolated = True
        if claim_ready:
            try:
                self._claim_intent_tickets(ws["path"], session_name,
                                           force=bool(claim_override))
            except Exception:
                self._discard_worktree(rec)
                self._rollback_submit(run_id)
                raise
        if kind == "execution":
            warnings = self._overlap_warnings(ws_id, str(task_text), run_id)
            if warnings:
                self.hub.emit("task_overlap_warning", workspace_id=ws_id,
                              run_id=run_id, data={"warnings": warnings})
        self.hub.emit("task_submitted", workspace_id=ws_id, run_id=run_id,
                      data={"task_text": str(task_text)[:200],
                            "session": session_name})
        rec.thread = threading.Thread(target=self._run_worker, args=(rec,),
                                      daemon=True)
        rec.thread.start()
        return run_id

    def _run_engine(self, ws: dict, run_id: str, preset_session: str = "",
                    workdir=None, state_root=None):
        """per-run 引擎（G8-M3/E2-4）：run_id + 会话（预设绑定）进构造
        （工厂不支持则回退）；E3-1/R5：隔离 run 传 workdir=worktree +
        state_root=主工作区（工厂不支持 state_root 则回退——不静默错装）。"""
        import inspect
        try:
            params = inspect.signature(self._factory).parameters
        except (TypeError, ValueError):
            params = {}
        kwargs = {}
        if "run_id" in params:
            kwargs["run_id"] = run_id
        if "preset_session" in params:
            kwargs["preset_session"] = str(preset_session or "")
        if state_root is not None and "state_root" in params:
            kwargs["state_root"] = state_root
        wd = str(workdir or ws["path"])
        if not kwargs:
            return self._factory(wd, ws["auto_confirm"])
        return self._factory(wd, ws["auto_confirm"], **kwargs)

    def _recovery_engine(self, ws_id: str, session: str = ""):
        """恢复引擎（G8-M3）：指向最新 run 状态；无 run 目录 → 旧根级引擎。

        E3-1/R5：隔离 run 按绑定标记路由（workdir=worktree、state_root=主）——
        无标记/标记损坏回落主工作区（诚实缺省）。
        §11.5-②：浏览器会话 overlay——缓释缺省时从历史补原 run 会话
        （仍缺 → 空=基键；memory 档重启后 partition 已清、persist 档无 overlay——语义等价）。
        """
        from wuxing.state import latest_run_id
        ws = self._workspace(ws_id)
        rid = latest_run_id(ws["path"])
        if not rid:
            return self._engine_for(ws_id)
        if not session:
            try:
                for entry in reversed(self.history(ws_id, limit=50)):
                    if str(entry.get("run_id", "")) == str(rid):
                        session = str(entry.get("session", "") or "")
                        break
            except Exception as exc:   # 历史不可读 → 按基键（诚实缺省）
                logger.debug("恢复会话查询失败（按基键）：%s", exc)
        import inspect
        try:
            params = inspect.signature(self._factory).parameters
        except (TypeError, ValueError):
            params = {}
        if "run_id" in params:
            kwargs = {"run_id": rid}
            if session and "preset_session" in params:
                kwargs["preset_session"] = str(session)
            wt = worktrees.run_worktree(ws["path"], rid)
            wd = str(wt) if wt else ws["path"]
            if wt is not None and "state_root" in params:
                kwargs["state_root"] = ws["path"]
            return self._factory(wd, ws["auto_confirm"], **kwargs)
        return self._engine_for(ws_id)

    @staticmethod
    def _text_similarity(a: str, b: str) -> float:
        """任务文本 2-gram Jaccard（并行自由任务的软重叠提示）。"""
        sa = "".join(str(a or "").split())[:400]
        sb = "".join(str(b or "").split())[:400]
        if not sa or not sb:
            return 0.0
        ta = {sa[i:i + 2] for i in range(len(sa) - 1)}
        tb = {sb[i:i + 2] for i in range(len(sb) - 1)}
        union = ta | tb
        return len(ta & tb) / len(union) if union else 0.0

    def _overlap_warnings(self, ws_id: str, text: str,
                          exclude_run: str | None = None) -> list[dict]:
        """自由任务并行 lint（G8-M3，软——不阻断）：与活动 run 的文本重叠。"""
        with self._lock:
            others = [r for r in self._runs.values()
                      if r.ws_id == ws_id and r.run_id != exclude_run
                      and r.status == "running"]
        out = []
        for r in others:
            sim = self._text_similarity(text, r.task_text)
            if sim >= 0.6:
                out.append({"run_id": r.run_id, "similarity": round(sim, 3),
                            "task_text": r.task_text[:120]})
        return out

    @staticmethod
    def _claim_intent_tickets(workdir, holder: str, force: bool = False) -> None:
        """提交期意图票据认领（G8-M2）：冲突 → BusyError（含持有者）。"""
        from wuxing import tickets as _tickets
        intended = [t for t in _tickets.load(workdir)
                    if str(t.get("status") or "") in ("ready", "running")]
        if not intended:
            return
        conflicts = [t for t in intended
                     if str(t.get("claimed_by") or "")
                     and str(t.get("claimed_by")) != holder]
        if conflicts and not force:
            details = "、".join(f"{t.get('id')}（{t.get('claimed_by')}）"
                                for t in conflicts)
            raise BusyError(f"票据已被认领：{details}"
                            "（claim_override=true 可强制移交）")
        _tickets.claim_many(workdir, [str(t.get("id")) for t in intended],
                            by=holder, force=force)

    def _rollback_submit(self, run_id: str) -> None:
        """提交期认领失败 → 回滚登记（不留半启动 run）。"""
        with self._lock:
            rec = self._runs.pop(run_id, None)
            if rec is None:
                return
            act = self._active.get(rec.ws_id)
            if act is not None:
                act.discard(run_id)
                if not act:
                    self._active.pop(rec.ws_id, None)
            if not self._active.get(rec.ws_id) and rec.ws_id in self._ws:
                self._ws[rec.ws_id]["status"] = "idle"

    def _discard_worktree(self, rec: "_Run") -> None:
        """回滚隔离 worktree（best-effort——失败留痕不阻断；不留半启动产物）。"""
        if not rec.worktree_path:
            return
        try:
            worktrees.remove(self._workspace(rec.ws_id)["path"], rec.run_id)
        except worktrees.WorktreeError as exc:
            logger.debug("worktree 回滚移除失败（留痕不阻断）：%s", exc)
        rec.worktree_path = ""
        rec.isolated = False

    # ---- E3-1/R5（T5）：worktree Review / Apply / Discard（壳面板与 API 经此） ----

    def _isolated_rec(self, run_id: str) -> "_Run":
        """隔离 run 定位（非隔离/无 worktree → NotFoundError）。"""
        rec = self._run(run_id)
        if not (rec.isolated and rec.worktree_path):
            raise NotFoundError("该 run 非隔离运行——无 worktree")
        return rec

    def worktree_review(self, run_id: str) -> dict:
        """隔离 run 变更视图（文件清单 + diff；供壳 Review 面板）。"""
        rec = self._isolated_rec(run_id)
        ws = self._workspace(rec.ws_id)
        try:
            files = worktrees.changes(ws["path"], rec.run_id)
            diff_text = worktrees.diff(ws["path"], rec.run_id)
        except worktrees.WorktreeError as exc:
            raise NotFoundError(str(exc)) from exc
        return {"run_id": rec.run_id, "path": rec.worktree_path,
                "status": rec.status, "files": files, "diff": diff_text}

    def worktree_apply(self, run_id: str) -> dict:
        """应用 worktree 变更到主检出（显式；冲突 loud 不自动消解）。"""
        rec = self._isolated_rec(run_id)
        ws = self._workspace(rec.ws_id)
        try:
            out = worktrees.apply(ws["path"], rec.run_id)
        except worktrees.WorktreeError as exc:
            self.hub.emit("worktree_apply_error", workspace_id=rec.ws_id,
                          run_id=rec.run_id, data={"error": str(exc)[:300]})
            raise ValueError(f"应用失败（冲突需人工处理）：{exc}") from exc
        self.hub.emit("worktree_applied", workspace_id=rec.ws_id,
                      run_id=rec.run_id, data={"files": out["files"]})
        return {"ok": True, "files": out["files"],
                "path": rec.worktree_path}

    def worktree_discard(self, run_id: str) -> dict:
        """丢弃 worktree（主检出零改动；已丢弃幂等）。"""
        rec = self._isolated_rec(run_id)
        ws = self._workspace(rec.ws_id)
        path = rec.worktree_path
        try:
            worktrees.discard(ws["path"], rec.run_id)
        except worktrees.WorktreeError as exc:
            raise ValueError(f"丢弃失败：{exc}") from exc
        rec.worktree_path = ""
        self.hub.emit("worktree_discarded", workspace_id=rec.ws_id,
                      run_id=rec.run_id, data={"path": path})
        return {"ok": True, "path": path}

    @staticmethod
    def _prepare_session(ws_path: pathlib.Path, session) -> str:
        """会话文件解析/新建（修复①）：指定名续写（不强制存在）；未指定自动新建
        `conversation-<ts>.jsonl`（冲突加序）；空文件占位——提交即可见。"""
        base = pathlib.Path(ws_path) / ".wuxing"
        raw = str(session or "").strip()
        if raw:
            if raw in (".", "..") or "/" in raw or "\\" in raw:
                raise ValueError(f"非法会话名：{raw!r}")
            name = raw if raw.endswith(".jsonl") else raw + ".jsonl"
            if name in ("provenance.jsonl", "trace.jsonl"):
                raise ValueError(f"保留会话名：{name}")
        else:
            stamp = int(time.time())
            name = f"conversation-{stamp}.jsonl"
            n = 2
            while (base / name).exists():
                name = f"conversation-{stamp}-{n}.jsonl"
                n += 1
        base.mkdir(parents=True, exist_ok=True)
        target = base / name
        if not target.exists():
            target.write_text("", encoding="utf-8")
        return name

    def _append_history(self, rec: "_Run", extra: dict | None = None) -> None:
        """任务完成即落盘（壳侧日志：跨重启可读；不含引擎内部细节）。

        extra：附加字段（如回滚标记 {"type": "rollback"}）。
        """
        if not self.history_path:
            return
        record = {
            "run_id": rec.run_id,
            "ws_id": rec.ws_id,
            "task_text": rec.task_text[:200],
            "status": rec.status,
            "started_at": round(rec.started_at, 3),
            "ended_at": round(time.time(), 3),
            "artifacts": len(getattr(rec.result, "artifacts", None) or []),
            "error": rec.error[:300],
            "isolated": bool(rec.isolated),
            "worktree_path": rec.worktree_path,
        }
        if extra:
            record.update(extra)
        line = json.dumps(record, ensure_ascii=False) + "\n"
        # Windows 文件占用（杀软/索引器）+ 同进程双工作区并行追加 → 串行化 + 重试。
        # 历史是观测设施，但「先落 history 再清 active」是快照一致性纪律（不得丢行）。
        with self._history_lock:
            for attempt in range(6):
                try:
                    self.history_path.parent.mkdir(parents=True, exist_ok=True)
                    with self.history_path.open("a", encoding="utf-8") as f:
                        f.write(line)
                    return
                except OSError:
                    time.sleep(0.05 * (attempt + 1))

    def history(self, ws_id: str, limit: int | None = 50) -> list[dict]:
        """任务历史（新→旧）；回滚标记合并入记录状态；标记行不单独输出。

        limit=None → 全量（搜索放宽窗口用，2026-09-22——FTS 触发前维持全扫）。
        """
        self._workspace(ws_id)
        if not (self.history_path and self.history_path.exists()):
            return []
        records: list[dict] = []
        rolled: set[str] = set()
        with self._history_lock:  # 与追加串行——防读到半写/空文件（双工作区并行抖动）
            text = read_text_retry(self.history_path)
        if text is None:
            return []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("ws_id") != ws_id:
                continue
            if rec.get("type") == "rollback":
                rolled.add(str(rec.get("run_id", "")))
                continue
            records.append(rec)
        # 2026-10-01：同 run 多行（挂起终态行 + 恢复完成追加行）——保留最后一条
        latest: dict[str, dict] = {}
        for rec in records:
            latest[str(rec.get("run_id", ""))] = rec
        records = list(latest.values())
        records.reverse()
        for r in records:
            if str(r.get("run_id", "")) in rolled:
                r["status"] = "rolled_back"
        if limit is None:
            return records
        return records[:max(1, int(limit))]

    def purge_history(self, run_id: str) -> int:
        """彻底删除：从壳侧任务日志移除该 run（含回滚标记行）；返回删除行数。"""
        if not (self.history_path and self.history_path.exists()):
            return 0
        with self._history_lock:
            return self._purge_history_locked(run_id)

    def _purge_history_locked(self, run_id: str) -> int:
        kept: list[str] = []
        removed = 0
        for line in self.history_path.read_text(
                encoding="utf-8", errors="replace").splitlines():
            s = line.strip()
            if not s:
                continue
            try:
                rec = json.loads(s)
            except ValueError:
                kept.append(line)
                continue
            if str(rec.get("run_id", "")) == run_id:
                removed += 1
                continue
            kept.append(line)
        if removed:
            self.history_path.write_text("\n".join(kept) + ("\n" if kept else ""),
                                         encoding="utf-8")
        return removed

    def set_auto_confirm(self, ws_id: str, flag: bool) -> dict:
        """工作区级自动确认开关（设置中心工作区域）——立即生效（重建引擎）。"""
        with self._lock:
            if ws_id not in self._ws:
                raise NotFoundError(f"未知工作区：{ws_id}")
            self._ws[ws_id]["auto_confirm"] = bool(flag)
            entry = dict(self._ws[ws_id])
        self._save_state()
        self.reload_engines(ws_id)
        return entry

    def reload_engines(self, ws_id: str | None = None) -> int:
        """配置变更后丢弃缓存的引擎（下个任务以新配置重建）；返回丢弃数量。"""
        with self._lock:
            if ws_id is None:
                n = len(self._engines)
                self._engines.clear()
                return n
            return 1 if self._engines.pop(ws_id, None) is not None else 0

    def skills(self, ws_id: str) -> list[dict]:
        """已装载技能清单（壳技能快捷选择用；经引擎公开契约）。"""
        engine = self._engine_for(ws_id)
        try:
            return engine.list_skills() or []
        except Exception:
            return []

    # ---- 管理面（阶段 5 · T5.1/T5.2——经引擎公开契约；需至少一个工作区） ----

    def _any_engine(self):
        """任意已打开工作区的引擎（管理面用；无工作区 → 明确报错）。"""
        with self._lock:
            ids = list(self._ws.keys())
        if not ids:
            raise NotFoundError("请先打开一个工作区（管理面需要引擎实例）")
        return self._engine_for(ids[0])

    def skills_index(self) -> list:
        return self._any_engine().list_skills() or []

    def skill_detail(self, name: str) -> dict | None:
        return self._any_engine().skill_detail(str(name))

    def skill_install(self, name: str, description: str, content: str,
                      scripts=None) -> dict:
        return self._any_engine().install_skill(str(name), str(description),
                                                str(content), scripts)

    def skill_remove(self, name: str) -> dict:
        return self._any_engine().remove_skill(str(name))

    def skill_set_enabled(self, name: str, enabled: bool) -> dict:
        return self._any_engine().set_skill_enabled(str(name), bool(enabled))

    def skill_discover(self, goal: str, constraints: str = "",
                       max_results: int = 5) -> dict:
        return self._any_engine().discover_skills(str(goal), str(constraints),
                                                  int(max_results))

    def mcp_status(self) -> dict:
        return self._any_engine().mcp_status()

    def mcp_reload(self) -> int:
        """按当前配置重建引擎（MCP 服务重载）——返回重建的引擎数。"""
        return self.reload_engines()

    def rollback(self, run_id: str, delete_artifacts: bool = False) -> dict:
        """任务回滚（用户验收设计）：清除该轮引擎状态（不可续跑/不落完成记录）；
        产物默认保留（安全语义）——显式 delete_artifacts 才删本任务产物。"""
        rec = self._run(run_id)
        ws = self._workspace(rec.ws_id)
        workdir = pathlib.Path(ws["path"]).resolve()
        removed: list[str] = []
        if delete_artifacts and rec.result is not None:
            for a in (getattr(rec.result, "artifacts", None) or []):
                rel = str(getattr(a, "path", "") or "")
                if not rel:
                    continue
                p = (workdir / rel).resolve()
                if p.is_relative_to(workdir) and p.is_file():
                    p.unlink()
                    removed.append(rel)
        # G8-M3：run 作用域状态优先；旧根级文件仅在没有 run 目录时清理
        from wuxing.state import latest_run_id, run_state_path
        state_file = run_state_path(workdir, rec.run_id)
        if state_file.is_file():
            state_file.unlink()
        if latest_run_id(workdir) is None:
            legacy = workdir / "task_state.json"
            if legacy.is_file():
                legacy.unlink()
        rec.status = "rolled_back"
        rec.result = None
        with self._lock:
            rec.pending_confirms = []
        self._append_history(rec, extra={"type": "rollback"})
        return {"ok": True, "run_id": run_id, "removed_artifacts": removed}

    def _append_unit_binding(self, ws_id: str, conversation: str,
                             unit_id: str, round_no: int) -> None:
        """碎片会话绑定记录（append-only sidecar）。

        设计 §3.3：`{conversation, unit_id, round, ts}`；预留 `key/reuse/file`
        （为「碎片上下文窗口自选」扩展位）。写入失败静默——绑定是观测/归属设施，
        不是生命线（与 history/titles 同口径）。
        """
        try:
            ws = self._workspace(ws_id)
            target = pathlib.Path(ws["path"]) / ".wuxing" / "unit-bindings.jsonl"
            rec = {"conversation": str(conversation), "unit_id": str(unit_id),
                   "round": int(round_no), "ts": round(time.time(), 3)}
            line = json.dumps(rec, ensure_ascii=False) + "\n"
            for attempt in range(3):
                try:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with target.open("a", encoding="utf-8") as f:
                        f.write(line)
                    return
                except OSError:
                    time.sleep(0.02 * (attempt + 1))
        except Exception as exc:  # 绑定失败绝不阻断任务
            logger.debug("运行绑定记录写出失败（不阻断）：%s", exc)

    def _run_worker(self, rec: _Run) -> None:
        try:
            # G8-M2/M3：per-run 引擎（不共享实例；run_id 进任务状态作用域）
            ws = self._workspace(rec.ws_id)
            engine = self._run_engine(
                ws, rec.run_id, rec.session,
                workdir=(rec.worktree_path or ws["path"]),
                state_root=(ws["path"] if rec.isolated else None))
            rec.engine = engine
            if rec.session:
                # 修复①（2026-09-20）：会话轮次记录——经引擎公开 API（start_session
                # 返回会话句柄，send 内记录轮次）；不直接 import 引擎内部模块。
                sess = engine.start_session(
                    conversation_path=pathlib.Path(ws["path"]) / ".wuxing" / rec.session)
                result = sess.send(rec.task_text,
                                   on_event=lambda e: self._bridge(rec, e),
                                   references=list(rec.references) or None,
                                   unit=rec.unit, overrides=rec.overrides)
                # 碎片绑定：send 返回即轮次已 append（round_no 为实际轮次）
                if rec.unit:
                    self._append_unit_binding(rec.ws_id, rec.session,
                                              rec.unit, sess.round_no)
            elif rec.references:
                result = engine.run_task(
                    rec.task_text, on_event=lambda e: self._bridge(rec, e),
                    references=list(rec.references), overrides=rec.overrides)
            else:
                result = engine.run_task(
                    rec.task_text, on_event=lambda e: self._bridge(rec, e),
                    overrides=rec.overrides)
            rec.result = result
            rec.status = str(getattr(result, "status", "unknown"))
            self._flush_terminal(rec)   # result 已落库——此刻事件才对客户端可见
        except Exception as exc:  # 引擎异常不拖垮服务
            self._discard_terminal(rec)
            rec.error = f"{type(exc).__name__}: {exc}"
            rec.status = "error"
            self.hub.emit("task_failed", workspace_id=rec.ws_id,
                          run_id=rec.run_id,
                          data={"error": rec.error[:300]})
        finally:
            # 先落 history、再清 active（与终态事件缓发同一原子性纪律）：
            # 客户端观察到「无活动任务」时，历史必已可查（修复并行用例时序抖动）
            self._append_history(rec)
            # E3-1/R5（T5）：隔离 run 终态 → worktree 就绪（壳 Review 面板入口）
            if rec.isolated and rec.worktree_path:
                self.hub.emit("worktree_ready", workspace_id=rec.ws_id,
                              run_id=rec.run_id,
                              data={"path": rec.worktree_path})
            self._end_op(rec)
            rec.done.set()

    def _bridge(self, rec: _Run, e) -> None:
        """引擎事件 → 壳事件（标准化名 + workspace/run 标注）。

        终态（task_done/task_cancelled）**缓发**：等 `rec.result` 落库后由
        `_flush_terminal` 统一发出——保证「事件可见 = 快照已含结果」（审查 I4）。
        """
        name = type(e).__name__
        etype = _EVENT_TYPE.get(name) or _snake(name)
        data = _event_data(e)
        if etype == "unit_needs_confirm":
            with self._lock:
                if not any(p["unit_id"] == data.get("unit_id")
                           for p in rec.pending_confirms):
                    rec.pending_confirms.append({
                        "unit_id": data.get("unit_id", ""),
                        "domain_id": data.get("domain_id", ""),
                        "reason": data.get("reason", ""),
                        "impact": data.get("impact") or {},
                        "view": data.get("view") or {}})
        elif etype == "unit_needs_answer":
            with self._lock:
                if not any(p.get("question_id") == data.get("question_id")
                           for p in rec.pending_answers):
                    rec.pending_answers.append({
                        "unit_id": data.get("unit_id", ""),
                        "domain_id": data.get("domain_id", ""),
                        "question_id": data.get("question_id", ""),
                        "questions": data.get("questions") or [],
                        "kind": data.get("kind", "")})
        elif etype == "question_answered":
            with self._lock:
                rec.pending_answers = [
                    p for p in rec.pending_answers
                    if not (p.get("question_id") == data.get("question_id")
                            and p.get("unit_id") == data.get("unit_id"))]
        elif etype in ("task_done", "task_cancelled"):
            if etype == "task_done" and data.get("status"):
                rec.status = str(data["status"])
            # 挂起（pending）不清空：确认门可能仍在等待用户（阶段 2.5）
            if not (etype == "task_done"
                    and data.get("status") == "pending"):
                with self._lock:
                    rec.pending_confirms = []
                    rec.pending_answers = []
            with self._lock:
                rec.deferred_terminal = (etype, data)   # 缓发（见 _flush_terminal）
            return
        self.hub.emit(etype, workspace_id=rec.ws_id, run_id=rec.run_id,
                      data=data)

    def _flush_terminal(self, rec: "_Run") -> None:
        """终态事件缓发出口——必须在 `rec.result` 落库之后调用。

        同时补全产物数（此刻 result 已存在——实时结果行不再依赖客户端旧快照）。
        """
        with self._lock:
            pending = rec.deferred_terminal
            rec.deferred_terminal = None
            result = rec.result
        if pending is None:
            return
        etype, data = pending
        if etype == "task_done" and result is not None:
            data = {**data,
                    "artifacts": len(getattr(result, "artifacts", None) or [])}
        self.hub.emit(etype, workspace_id=rec.ws_id, run_id=rec.run_id,
                      data=data)

    def _discard_terminal(self, rec: "_Run") -> None:
        """丢弃缓发终态（异常路径——不得发出与结果不符的事件）。"""
        with self._lock:
            rec.deferred_terminal = None

    def _ensure_terminal(self, rec: "_Run") -> None:
        """W5.1：命令 worker 结束补发终态事件（resume 路径引擎不发 TaskDone）。

        仅在既无缓发终态、且状态非 running/error 时合成（不伪造异常终态）。
        """
        with self._lock:
            if rec.deferred_terminal is not None:
                return
            status = str(rec.status or "")
            if status in ("", "running", "error"):
                return
            rec.deferred_terminal = ("task_done", {"status": status})
        self._flush_terminal(rec)

    def get_run(self, run_id: str) -> dict:
        """公开读取运行记录（任务菜单/回滚链路用）。"""
        return self._run(run_id).public()

    def wait(self, run_id: str, timeout: float = 30) -> dict:
        rec = self._run(run_id)
        rec.done.wait(timeout)
        return rec.public()

    def _run(self, run_id: str) -> _Run:
        with self._lock:
            rec = self._runs.get(run_id)
        if rec is None:
            raise NotFoundError(f"未知运行：{run_id}")
        return rec

    # ---- 命令（同步——ThreadingHTTPServer 每请求一线程，不阻塞接受循环） ----
    def _cmd_lock_for(self, ws_id: str) -> threading.Lock:
        with self._cmd_guard:
            lock = self._cmd_locks.get(ws_id)
            if lock is None:
                lock = threading.Lock()
                self._cmd_locks[ws_id] = lock
            return lock

    def _begin_op(self, rec: "_Run") -> None:
        """执行类操作登记（W5.2 + G8-M2）：原子 check+register（执行槽）。

        确认/恢复/提交的执行语义属引擎写操作（task_state 读改写）——执行类
        同工作区必须互斥（设计轮不受影响，可并行）；否则并发 worker 以旧
        task_state 覆盖 attempts/units（A 复跑登记项）。
        """
        with self._lock:
            act = self._active.get(rec.ws_id) or set()
            # W5.2：同一 run 重复发起确认/续跑 → 拒绝（防并发覆盖）
            if rec.run_id in act:
                raise BusyError("该任务正在运行——请等待完成或取消")
            # G8-M3：任务状态按 run 隔离——操作只需防「同一 run 重复发起」
            self._active.setdefault(rec.ws_id, set()).add(rec.run_id)
            if rec.ws_id in self._ws:
                self._ws[rec.ws_id]["status"] = "running"

    def _end_op(self, rec: "_Run") -> None:
        """释放操作登记（幂等；仅释放自己的登记）。"""
        with self._lock:
            act = self._active.get(rec.ws_id)
            if act is None or rec.run_id not in act:
                return
            act.discard(rec.run_id)
            if not act:
                self._active.pop(rec.ws_id, None)
            if not self._active.get(rec.ws_id) and rec.ws_id in self._ws:
                self._ws[rec.ws_id]["status"] = "idle"

    def _spawn_command(self, rec: "_Run", work) -> None:
        """确认/续跑走工作线程（设计 §4.4：不阻塞 HTTP；同工作区串行）。

        W5.1：正常结束且引擎未发终态（如 resume 路径）→ 合成 task_done
        （UI 收口）；异常路径不伪造终态（*_error 事件已由各 work 发出）。
        """
        def runner():
            with self._cmd_lock_for(rec.ws_id):
                completed = False
                try:
                    work()
                    completed = True
                finally:
                    self._end_op(rec)   # W5.2：释放操作登记（异常也释放）
                    if completed:
                        self._ensure_terminal(rec)
                        # 2026-10-01：确认/续跑完成补写历史——否则 tasks.jsonl
                        # 永停 pending（磁盘 task_state 已 done，壳历史没更新）
                        self._append_history(rec)
        threading.Thread(target=runner, daemon=True).start()

    def confirm(self, run_id: str, items, reason: str = "") -> dict:
        rec = self._run(run_id)
        pairs = [tuple(i) for i in items]
        with self._lock:
            known = {p["unit_id"] for p in rec.pending_confirms}
        unknown = [u for u, _ in pairs if u not in known]
        if unknown:
            raise NotFoundError(
                f"未知或已处理的待确认单元：{', '.join(unknown)}")
        self._begin_op(rec)   # W5.2：确认 worker 期间拒绝其它执行类操作
        try:
            engine = rec.engine or self._engine_for(rec.ws_id)
        except Exception:
            self._end_op(rec)
            raise

        def work():
            try:
                result = engine.confirm_units(
                    pairs, reason=reason,
                    on_event=lambda e: self._bridge(rec, e))
                rec.result = result          # 内存记录同步（否则快照仍为挂起态）
                rec.status = str(getattr(result, "status", rec.status))
                self._flush_terminal(rec)
            except Exception as exc:  # 引擎异常 → 壳事件（不拖垮服务）
                self._discard_terminal(rec)
                self.hub.emit("confirm_error", workspace_id=rec.ws_id,
                              run_id=rec.run_id,
                              data={"error": f"{type(exc).__name__}: {exc}"[:300]})

        # 真测 REAL-14：确认即清理（在续跑前）——续跑期间重新挂起的事件必须保留
        # （原清理在 worker 的 finally：按 unit_id 把“续跑重挂的同 id 条目”一并抹掉）
        with self._lock:
            done_ids = {u for u, _ in pairs}
            rec.pending_confirms = [p for p in rec.pending_confirms
                                    if p["unit_id"] not in done_ids]
        try:
            self._spawn_command(rec, work)
        except Exception:
            self._end_op(rec)
            raise
        return rec.public()

    def answer(self, run_id: str, unit_id: str, question_id: str,
               answer: str, source: str = "text", reason: str = "") -> dict:
        """E2-5（A10）：答复提问并续跑挂起单元（壳命令路由）。

        镜像 confirm 口径：待答集同步校验（未知/已处理 → NotFoundError）；
        答复即清理（REAL-14——续跑重挂的新问题必须保留）；worker 内调
        engine.answer_unit（同工作区执行类互斥）。
        """
        rec = self._run(run_id)
        with self._lock:
            match = next((p for p in rec.pending_answers
                          if p.get("unit_id") == unit_id
                          and p.get("question_id") == question_id), None)
        if match is None:
            raise NotFoundError(
                f"未知或已处理的待答问题：{unit_id}/{question_id}")
        self._begin_op(rec)   # W5.2：答复 worker 期间拒绝其它执行类操作
        try:
            engine = rec.engine or self._engine_for(rec.ws_id)
        except Exception:
            self._end_op(rec)
            raise

        def work():
            try:
                result = engine.answer_unit(
                    unit_id, question_id, answer, source=source, reason=reason,
                    on_event=lambda e: self._bridge(rec, e))
                rec.result = result          # 内存记录同步（否则快照仍为挂起态）
                rec.status = str(getattr(result, "status", rec.status))
                self._flush_terminal(rec)
            except Exception as exc:  # 引擎异常 → 壳事件（不拖垮服务）
                self._discard_terminal(rec)
                self.hub.emit("answer_error", workspace_id=rec.ws_id,
                              run_id=rec.run_id,
                              data={"error": f"{type(exc).__name__}: {exc}"[:300]})

        # REAL-14 口径：答复即清理（在续跑前）——续跑重挂的新问题必须保留
        with self._lock:
            rec.pending_answers = [
                p for p in rec.pending_answers
                if not (p.get("unit_id") == unit_id
                        and p.get("question_id") == question_id)]
        try:
            self._spawn_command(rec, work)
        except Exception:
            self._end_op(rec)
            raise
        return rec.public()

    def resume(self, run_id: str) -> dict:
        rec = self._run(run_id)
        self._begin_op(rec)   # W5.2：忙检查 + 登记（resume 同属执行类写操作）
        try:
            engine = rec.engine or self._engine_for(rec.ws_id)
        except Exception:
            self._end_op(rec)
            raise

        def work():
            try:
                result = engine.resume_task(on_event=lambda e: self._bridge(rec, e))
                rec.result = result
                rec.status = str(getattr(result, "status", rec.status))
                self._flush_terminal(rec)
            except Exception as exc:
                self._discard_terminal(rec)
                self.hub.emit("resume_error", workspace_id=rec.ws_id,
                              run_id=rec.run_id,
                              data={"error": f"{type(exc).__name__}: {exc}"[:300]})

        try:
            self._spawn_command(rec, work)
        except Exception:
            self._end_op(rec)
            raise
        return rec.public()

    def resume_workspace(self, ws_id: str) -> dict:
        """M7 #8（A3）：重启后按工作区续跑（引擎从 task_state.json 恢复）。

        与 submit 同并发纪律：活动任务/挂起确认/全局并发上限均拒绝。
        """
        ws = self._workspace(ws_id)
        with self._lock:
            if self._active.get(ws_id):
                raise BusyError("该工作区已有活动任务")
            if any(r.ws_id == ws_id and r.pending_confirms
                   for r in self._runs.values()):
                raise BusyError("该工作区有待确认任务，请先处理确认门")
            if sum(len(s) for s in self._active.values()) >= self.max_concurrent:
                raise BusyError("全局并发已达上限")
            run_id = uuid.uuid4().hex[:12]
            rec = _Run(run_id, ws_id, task_text="", ws_path=ws["path"])
            rec.kind = "recovery"
            self._runs[run_id] = rec
        try:
            self._begin_op(rec)   # 操作登记（含 status=running）
        except BusyError:
            with self._lock:
                self._runs.pop(run_id, None)
            raise
        self.hub.emit("task_submitted", workspace_id=ws_id, run_id=run_id,
                      data={"task_text": ""})
        engine = self._recovery_engine(ws_id)
        rec.engine = engine

        def work():
            try:
                result = engine.resume_task(
                    on_event=lambda e: self._bridge(rec, e))
                rec.result = result
                rec.status = str(getattr(result, "status", rec.status))
                self._flush_terminal(rec)
            except Exception as exc:
                self._discard_terminal(rec)
                rec.error = f"{type(exc).__name__}: {exc}"
                rec.status = "error"
                self.hub.emit("task_failed", workspace_id=ws_id,
                              run_id=run_id,
                              data={"error": rec.error[:300]})
            finally:
                self._append_history(rec)
                self._end_op(rec)
                rec.done.set()

        self._spawn_command(rec, work)
        return rec.public()

    def abandon_workspace(self, ws_id: str) -> dict:
        """M7 #8（A3）：放弃重启后残留的挂起状态（改名留痕，不物理删除）。"""
        ws = self._workspace(ws_id)
        wd = pathlib.Path(ws["path"])
        from wuxing.state import latest_state_path
        targets = []
        latest = latest_state_path(wd)
        if latest.is_file():
            targets.append(latest)
        legacy = wd / "task_state.json"
        if legacy.is_file() and legacy != latest:
            targets.append(legacy)
        if not targets:
            return {"ok": True, "abandoned": False}
        stamp = int(time.time())
        renamed = []
        for p in targets:
            dest = p.with_name(f"task_state.abandoned-{stamp}.json")
            p.rename(dest)
            renamed.append(dest.name)
        return {"ok": True, "abandoned": True, "path": renamed[-1]}

    def cancel(self, run_id: str) -> dict:
        rec = self._run(run_id)
        if rec.engine is not None:
            rec.engine.cancel_task()
        return rec.public()

    # ---- 快照（客户端重连/首屏） ----
    def snapshot(self, ws_id: str) -> dict:
        ws = self._workspace(ws_id)
        with self._lock:
            act = self._active.get(ws_id) or set()
            run_id = None
            if act:
                run_id = max(act, key=lambda rid: (self._runs[rid].started_at,
                                                   self._runs[rid].submit_seq))
            last = None
            for r in reversed(list(self._runs.values())):
                if r.ws_id == ws_id:
                    last = r
                    break
        active = self._runs[run_id].public() if run_id else None
        tail = active or (last.public() if last else {})
        units = []
        src = self._runs.get(run_id) if run_id else last
        result = getattr(src, "result", None) if src is not None else None
        for u in (getattr(result, "units", None) or []):
            units.append({"unit_id": getattr(u, "unit_id", ""),
                          "domain_id": getattr(u, "domain_id", ""),
                          "status": getattr(u, "status", ""),
                          "failure_class": getattr(u, "failure_class", "")})
        return {"workspace": dict(ws),
                "active_run": active,
                "result": tail.get("result"),
                "task_text": tail.get("task_text", ""),
                "run_id": tail.get("run_id", ""),
                "session": tail.get("session", ""),
                "units": units,
                "pending_confirms": tail.get("pending_confirms", []),
                "pending_answers": tail.get("pending_answers", []),
                "pending_resume": (self._pending_resume(ws)
                                   if run_id is None and last is None else None),
                "last_seq": self.hub.info()["last_seq"]}

    def _pending_resume(self, ws: dict):
        """M7 #8（A3）：重启后挂起确认的可发现性（磁盘 task_state.json）。

        仅当内存无 run 时调用；返回 {task_text, units:[{unit_id, domain_id}]}
        或 None（无可恢复状态——不造假）。
        """
        try:
            from wuxing.state import latest_state_path, load_state
            st = load_state(latest_state_path(pathlib.Path(ws["path"])))
        except Exception:
            # 状态文件缺失/损坏 → None（无待确认单元）
            return None
        pend = [u for u in st.units
                if str(getattr(u, "status", "")) == "needs_confirm"]
        if not pend and str(st.status) != "pending":
            return None
        return {"task_text": str(st.task_text)[:200],
                "units": [{"unit_id": str(getattr(u, "unit_id", "")),
                           "domain_id": str(getattr(u, "domain_id", ""))}
                          for u in pend]}

    def shutdown(self, timeout: float = 3) -> None:
        with self._lock:
            threads = [r.thread for r in self._runs.values() if r.thread]
        for t in threads:
            t.join(timeout=timeout)
