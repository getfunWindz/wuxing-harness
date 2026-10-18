"""观测/搜索/维护/关于路由（Q1：自 api.py register_api 逐字迁移）。"""
import json
import logging
import pathlib

from wuxing.config_contract import ConfigError, effective_config
from wuxing.shell.web import version
from wuxing.shell.web.server import error_response, json_response

from .base import _INTERNAL_JSONL, _guard

logger = logging.getLogger(__name__)

# P2 最小版（T6.2）：通知中心关注的事件类型（列表与角标同源）
_NOTICE_TYPES = ("task_done", "task_failed", "task_cancelled", "safety_blocked")


def _read_jsonl(path: pathlib.Path, limit: int = 200) -> list[dict]:
    """容错读 JSONL 尾部（阶段 4 观测）：缺文件空表、损坏行跳过、只读。

    实现：最多读文件尾部 512KB（大日志不整读）。
    """
    try:
        if not path.exists():
            return []
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 512 * 1024))
            raw = f.read().decode("utf-8", "replace")
    except OSError:
        return []
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    if len(lines) > limit:
        lines = lines[-limit:]
    out = []
    for ln in lines:
        try:
            obj = json.loads(ln)
        except json.JSONDecodeError:
            continue  # 损坏行跳过（韧性惯例）
        if isinstance(obj, dict):
            out.append(obj)
    return out


def register(server, ctx) -> None:
    manager = ctx.manager
    hub = ctx.hub

    @_guard
    def h_ws_files(req):
        """工作区文件浏览（阶段 5 · ⑧：参考文件选择器）——限定 workdir、隐藏目录跳过。"""
        ws = manager.get_workspace(req.params["ws"])
        root = pathlib.Path(ws["path"]).resolve()
        rel = (req.query.get("path") or "").strip()
        target = (root / rel).resolve() if rel else root
        try:
            target.relative_to(root)
        except ValueError:
            return error_response(403, "denied", "路径越界")
        if not target.is_dir():
            return error_response(404, "not_found", "目录不存在")
        dirs, files = [], []
        try:
            for entry in sorted(target.iterdir(), key=lambda p: p.name.lower()):
                if entry.name.startswith("."):
                    continue
                item = {"name": entry.name,
                        "path": entry.relative_to(root).as_posix()}
                (dirs if entry.is_dir() else files).append(item)
                if len(dirs) + len(files) >= 200:
                    break
        except OSError as exc:
            return error_response(403, "denied", f"无法读取目录：{exc}")
        return json_response({"path": rel, "dirs": dirs, "files": files})

    @_guard
    def h_observe_provenance(req):
        root = pathlib.Path(manager.get_workspace(req.params["ws"])["path"])
        rows = _read_jsonl(root / ".wuxing" / "provenance.jsonl", 2000)
        return json_response({"rows": rows})

    @_guard
    def h_observe_trace(req):
        root = pathlib.Path(manager.get_workspace(req.params["ws"])["path"])
        limit = max(1, min(int(req.query.get("limit") or 300), 2000))
        rows = _read_jsonl(root / ".wuxing" / "trace.jsonl", limit)
        unit = (req.query.get("unit") or "").strip()
        if unit:
            rows = [r for r in rows if str(r.get("unit_id")) == unit]
        return json_response({"rows": rows})

    @_guard
    def h_decisions(req):
        """#2 T-5：决策历史（trace 审计对还原——只读）。"""
        from wuxing import decision_log
        root = pathlib.Path(manager.get_workspace(req.params["ws"])["path"])
        limit = max(1, min(int(req.query.get("limit") or 200), 1000))
        return json_response(decision_log.load_decisions(root, limit=limit))

    @_guard
    def h_events_log(req):
        limit = max(1, min(int(req.query.get("tail") or 200), 2000))
        shell_dir = (pathlib.Path(manager.state_path).parent
                     if manager.state_path
                     else pathlib.Path.home() / ".wuxing" / "shell")
        return json_response({"rows": _read_jsonl(shell_dir / "events.jsonl", limit)})

    @_guard
    def h_notifications(req):
        """通知历史：壳事件日志过滤（最新在前）；unread = seq > since 的通知数。

        items 为全量最近窗口（不过滤 since——列表/历史可见）；角标与列表同源。
        """
        since_raw = req.query.get("since")
        since = 0
        if since_raw not in (None, ""):
            try:
                since = int(since_raw)
            except ValueError:
                return error_response(422, "invalid", "since 必须为整数")
        try:
            limit = int(req.query.get("limit") or 50)
        except ValueError:
            limit = 50
        limit = max(1, min(limit, 200))
        shell_dir = (pathlib.Path(manager.state_path).parent
                     if manager.state_path
                     else pathlib.Path.home() / ".wuxing" / "shell")
        rows = _read_jsonl(shell_dir / "events.jsonl", 2000)
        names = {w["id"]: w["name"] for w in manager.list_workspaces()}
        items = []
        for ev in rows:
            etype = ev.get("type")
            if etype not in _NOTICE_TYPES:
                continue
            data = ev.get("data") or {}
            if etype == "task_done" and str(data.get("status") or "") == "pending":
                continue   # 待确认不是通知（由确认门/角标表达——审查 I6）
            item = {"seq": ev.get("seq"), "ts": ev.get("ts"), "type": etype,
                    "level": "info",
                    "workspace_id": ev.get("workspace_id", ""),
                    "workspace_name": names.get(ev.get("workspace_id"), ""),
                    "run_id": ev.get("run_id", ""),
                    "status": "", "reason": "", "tool": ""}  # 契约键恒在（P2-M4）
            if etype == "safety_blocked":
                item["level"] = "warn"
                item["reason"] = data.get("reason", "")
                item["tool"] = data.get("tool", "")
            else:
                status = str(data.get("status") or "")
                item["status"] = status
                if etype == "task_failed" or status in ("failed", "partial"):
                    item["level"] = "warn"
                elif etype == "task_done":
                    item["level"] = "ok"
            items.append(item)
        unread = sum(1 for it in items if (it.get("seq") or 0) > since)
        return json_response({"items": items[-limit:][::-1], "unread": unread,
                              "last_seq": hub.info()["last_seq"]})

    @_guard
    def h_brain(req):
        """智脑统计（只读）：案例容量/分级/成功率/最近案例。

        brain_enabled=False 也收集（展示只读）；数据源 workdir/brain_memory.json。
        """
        ws = manager.get_workspace(req.params["ws"])
        root = pathlib.Path(ws["path"])
        cases = []
        p = root / "brain_memory.json"
        if p.is_file():
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(raw, dict) and isinstance(raw.get("cases"), list):
                    cases = raw["cases"]
            except (OSError, ValueError):
                cases = []   # 损坏不崩（韧性惯例）
        tiers = {"high": 0, "normal": 0, "low": 0}
        attempts = success = 0
        recent = []
        for c in cases:
            if not isinstance(c, dict):
                continue
            tier = c.get("tier") if c.get("tier") in tiers else "normal"
            tiers[tier] += 1
            a = max(0, int(c.get("attempts", 0) or 0))
            attempts += a
            if "success_count" in c:
                sc = max(0, int(c.get("success_count", 0) or 0))
            else:
                sc = a if c.get("success") else 0
            success += sc
            recent.append({
                "key": str(c.get("key", ""))[:120],
                "domain": str(c.get("domain", "")),
                "model": str(c.get("model", "")), "tier": tier,
                "attempts": a,
                "success_rate": round(sc / a, 4) if a else 0.0,
                "last_at": c.get("last_at", 0),
            })
        recent.sort(key=lambda x: x["last_at"], reverse=True)
        try:
            eff = effective_config(root)
            enabled = bool(eff["values"].get("brain_enabled", False))
            capacity = int(eff["values"].get("brain_max_cases", 500))
        except (ConfigError, ValueError, TypeError):
            enabled, capacity = False, 500
        return json_response({
            "cases": len(cases), "attempts": attempts,
            "success_count": success,
            "success_rate": round(success / attempts, 4) if attempts else 0.0,
            "tiers": tiers, "capacity": capacity, "enabled": enabled,
            "recent": recent[:10],
        })

    @_guard
    def h_reports(req):
        """评估报告列表（只读）：workdir/docs/*.md；内容经 artifacts 路由读取。"""
        ws = manager.get_workspace(req.params["ws"])
        docs = pathlib.Path(ws["path"]) / "docs"
        reports = []
        if docs.is_dir():
            entries = []
            try:
                for p in docs.glob("*.md"):
                    if p.is_file():
                        st = p.stat()
                        entries.append({"name": p.name,
                                        "path": f"docs/{p.name}",
                                        "size": st.st_size,
                                        "mtime": round(st.st_mtime, 3)})
            except OSError:
                entries = []
            entries.sort(key=lambda x: (-x["mtime"], x["name"]))
            reports = entries[:100]
        return json_response({"reports": reports})

    @_guard
    def h_search(req):
        """全库搜索（阶段 5/6）：任务文本（壳侧历史）+ 会话（名称/首部内容）。

        壳只读消费：tasks.jsonl（壳状态）+ <workdir>/.wuxing/*.jsonl（会话；内部 jsonl 排除）。
        """
        q = (req.query.get("q") or "").strip()   # query 已被服务端 parse_qs 解码
        limit = max(1, min(int(req.query.get("limit") or 30), 100))
        ql = q.lower()
        tasks: list[dict] = []
        sessions: list[dict] = []
        if q:
            for w in manager.list_workspaces():
                # 放宽搜索窗口（2026-09-22 · FTS 前置）：任务历史全量扫描
                # （原每工作区仅最近 200 条——覆盖优先；FTS 触发后再上索引/分页）
                for rec in manager.history(w["id"], limit=None):
                    text = str(rec.get("task_text") or "")
                    if ql in text.lower():
                        tasks.append({
                            "kind": "task", "ws_id": w["id"],
                            "ws_name": w["name"], "run_id": rec.get("run_id"),
                            "text": text[:160],
                            "status": rec.get("status"),
                            "ts": rec.get("started_at"),
                        })
                        if len(tasks) >= limit:
                            break
                if len(tasks) >= limit:
                    break
            for w in manager.list_workspaces():
                base = pathlib.Path(w["path"]) / ".wuxing"
                if not base.is_dir():
                    continue
                for p in sorted(base.glob("*.jsonl")):
                    if p.name in _INTERNAL_JSONL:
                        continue
                    if len(sessions) >= limit:
                        break
                    snippet = None
                    if ql in p.name.lower():
                        snippet = ""
                    else:
                        try:
                            # 放宽搜索窗口（2026-09-22）：会话全文扫描
                            # （原仅前 60 行——覆盖优先，命中即停）
                            with open(p, "r", encoding="utf-8",
                                      errors="replace") as f:
                                for line in f:
                                    if ql in line.lower():
                                        snippet = _snippet(line)
                                        break
                        except OSError:
                            continue
                    if snippet is not None:
                        sessions.append({
                            "kind": "session", "ws_id": w["id"],
                            "ws_name": w["name"], "name": p.name,
                            "snippet": snippet[:160],
                            "mtime": round(p.stat().st_mtime, 3),
                        })
        return json_response({"tasks": tasks[:limit],
                              "sessions": sessions[:limit]})

    def _snippet(line: str) -> str:
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                c = obj.get("content")
                if isinstance(c, str) and c.strip():
                    return c.strip()
        except ValueError as exc:
            logger.debug("会话行非 JSON（原文兜底显示）：%s", exc)
        return line.strip()

    @_guard
    def h_bench_cache(req):
        """缓存量化复验（T4.1）——子进程运行（壳不 import 引擎内部）。"""
        import subprocess
        import sys
        try:
            proc = subprocess.run([sys.executable, "-m", "wuxing.cache_bench"],
                                  capture_output=True, timeout=180, check=False)
            out = (proc.stdout or b"").decode("utf-8", "replace").strip()
            data = json.loads(out) if out else {}
            return json_response({"ok": proc.returncode == 0, "result": data})
        except Exception as exc:  # 复验失败不拖垮服务
            return error_response(500, "bench_failed", str(exc)[:300])

    @_guard
    def h_about(req):
        """M7 C1（MG-15）：关于与诊断（只读——版本/环境/路径）。"""
        import platform as _platform
        shell_dir = (pathlib.Path(manager.state_path).parent
                     if manager.state_path
                     else pathlib.Path.home() / ".wuxing" / "shell")
        return json_response({
            "shell_version": version.SHELL_VERSION,
            "api_version": version.API_VERSION,
            "python": _platform.python_version(),
            "platform": _platform.platform(),
            "data_dir": str(shell_dir),
            "log_dir": str(shell_dir),
            "workspace_count": len(manager.list_workspaces()),
            "assemblies": manager.assemblies_summary(),
        })

    @_guard
    def h_maintenance(req):
        """数据与维护：数据目录/缀存文件概览（只读展示；清理走 clean 端点）。"""
        shell_dir = (pathlib.Path(manager.state_path).parent
                     if manager.state_path else pathlib.Path.home() / ".wuxing")
        user_dir = pathlib.Path.home() / ".wuxing"
        events = shell_dir / "events.jsonl"
        skills_dir = user_dir / "skills"
        try:
            skills_count = sum(1 for p in skills_dir.iterdir() if p.is_dir())
        except OSError:
            skills_count = 0
        out = {
            "user_dir": str(user_dir),
            "shell_dir": str(shell_dir),
            "skills": {"path": str(skills_dir), "count": skills_count},
            "events": {"path": str(events),
                       "size": events.stat().st_size if events.exists() else 0},
            "workspaces": [],
        }
        ws_id = req.query.get("ws")
        if ws_id:
            ws = manager.get_workspace(ws_id)
            wd = pathlib.Path(ws["path"])
            caches = []
            for name in ("reply_cache.json", "shape_cache.json",
                         "brain_memory.json"):
                p = wd / name
                caches.append({"name": name,
                               "size": p.stat().st_size if p.exists() else 0})
            from wuxing.state import latest_state_path
            state = latest_state_path(wd)
            out["workspace"] = {"id": ws["id"], "path": str(wd),
                                "caches": caches,
                                "has_state": state.is_file()}
        return json_response(out)

    @_guard
    def h_maintenance_clean(req):
        """清理（二次确认由 UI 承担）：workspace_cache = 删壳/引擎缓存文件；
        shell_events = 清空事件日志。永不碰用户产物。"""
        body = req.json() or {}
        target = str(body.get("target") or "")
        removed = []
        if target == "workspace_cache":
            ws_id = body.get("ws")
            if not ws_id:
                return error_response(422, "invalid", "需要 ws 参数")
            ws = manager.get_workspace(ws_id)
            wd = pathlib.Path(ws["path"]).resolve()
            for name in ("reply_cache.json", "shape_cache.json"):
                p = (wd / name).resolve()
                if p.is_relative_to(wd) and p.is_file():
                    p.unlink()
                    removed.append(name)
            manager.reload_engines(ws_id)
        elif target == "shell_events":
            shell_dir = (pathlib.Path(manager.state_path).parent
                         if manager.state_path
                         else pathlib.Path.home() / ".wuxing")
            ev = shell_dir / "events.jsonl"
            if ev.is_file():
                ev.write_text("", encoding="utf-8")
                removed.append("events.jsonl")
        else:
            return error_response(422, "invalid", "未知清理目标")
        return json_response({"ok": True, "removed": removed})

    server.add_route(
        "GET",
        r"^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/files$",
        h_ws_files)
    server.add_route(
        "GET",
        r"^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/observe/provenance$",
        h_observe_provenance)
    server.add_route(
        "GET",
        r"^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/observe/trace$",
        h_observe_trace)
    server.add_route(
        "GET",
        r"^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/decisions$",
        h_decisions)
    server.add_route("GET", r"^/api/v1/events/log$", h_events_log)
    server.add_route("GET", r"^/api/v1/notifications$", h_notifications)
    server.add_route(
        "GET", r"^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/brain$", h_brain)
    server.add_route(
        "GET", r"^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/reports$", h_reports)
    server.add_route("GET", r"^/api/v1/search$", h_search)
    server.add_route(
        "POST",
        r"^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/bench/cache$",
        h_bench_cache)
    server.add_route("GET", r"^/api/v1/about$", h_about)
    server.add_route("GET", r"^/api/v1/maintenance$", h_maintenance)
    server.add_route("POST", r"^/api/v1/maintenance/clean$",
                     h_maintenance_clean)
