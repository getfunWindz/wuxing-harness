"""会话列表/详情/轮次/碎片/轨迹/标题/重命名/导出/分支路由（Q1：自 api.py 逐字迁移）。"""
import json
import pathlib

from wuxing.shell.web import session_titles, session_view
from wuxing.shell.web.server import error_response, json_response
from wuxing.shell.web.state import norm_path

from .base import _INTERNAL_JSONL, _guard, _session_path


def register(server, ctx) -> None:
    manager = ctx.manager
    recycle = ctx.recycle
    title_runner = ctx.title_runner

    @_guard
    def h_sessions(req):
        ws = manager.get_workspace(req.params["ws"])
        base = pathlib.Path(ws["path"]) / ".wuxing"
        hidden = recycle.hidden_session_paths(ws["path"])
        out = []
        if base.is_dir():
            # 只列会话文件（*.jsonl 排除引擎内部观测文件）
            # 观测文件（provenance/trace 等）；归档/删除的会话不在活动列表
            titles = session_titles.load_titles(ws["path"])
            lineage = session_view.branch_lineage(ws["path"])
            for p in sorted(base.glob("*.jsonl")):
                if p.is_file() and p.name not in _INTERNAL_JSONL \
                        and norm_path(p) not in hidden:
                    st = p.stat()
                    out.append({"name": p.name, "size": st.st_size,
                                "mtime": round(st.st_mtime, 3),
                                "path": str(p.resolve()),
                                "title": titles.get(p.name, ""),
                                "branched_from": lineage.get(p.name)})
        return json_response({"sessions": out})

    @_guard
    def h_session(req):
        ws = manager.get_workspace(req.params["ws"])
        base = (pathlib.Path(ws["path"]) / ".wuxing").resolve()
        name = req.params.get("name", "")
        if not name.startswith("conversation") or "/" in name or "\\" in name:
            return error_response(404, "not_found", f"会话不存在：{name}")
        target = (base / name).resolve()
        if not target.is_relative_to(base) or not target.is_file():
            return error_response(404, "not_found", f"会话不存在：{name}")
        rows = []
        for line in target.read_text(encoding="utf-8",
                                     errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue  # 破损行跳过（历史可读性优先）
            if str(row.get("type") or "") in ("branch", "compaction"):
                continue  # G1/G7：承接/压缩行不是轮次（不渲染进会话流）
            rows.append(row)
        return json_response({"name": req.params.get("name", ""),
                              "rows": rows[-500:]})

    # —— 工作区域轮次/碎片会话/轨迹（2026-09-21 · 只读聚合）——
    @_guard
    def h_session_rounds(req):
        root = pathlib.Path(manager.get_workspace(req.params["ws"])["path"])
        name = req.params.get("name", "")
        if ("/" in name or "\\" in name or not name.endswith(".jsonl")
                or name in _INTERNAL_JSONL):
            return error_response(404, "not_found", f"会话不存在：{name}")
        return json_response(session_view.session_rounds(root, name))

    @_guard
    def h_unit_session(req):
        root = pathlib.Path(manager.get_workspace(req.params["ws"])["path"])
        return json_response(session_view.unit_session(
            root, req.params.get("unit", "")))

    @_guard
    def h_trajectory(req):
        root = pathlib.Path(manager.get_workspace(req.params["ws"])["path"])
        session = (req.query.get("session") or "").strip()
        return json_response(session_view.trajectory(root, session))

    @_guard
    def h_conversations_branch(req):
        """G1：从既有会话轮派生新会话（fork 式——承接摘要 + 血缘）。

        body: {session, from_round, mode?, summary?, focus?}；
        非法入参/引擎校验失败 → 422（_guard 统一映射 ValueError）。
        """
        manager.get_workspace(req.params["ws"])
        body = req.json() or {}
        session = str(body.get("session") or "").strip()
        if (not session or "/" in session or "\\" in session
                or session in _INTERNAL_JSONL):
            return error_response(422, "invalid", f"非法会话名：{session}")
        try:
            from_round = int(body.get("from_round") or 0)
        except (TypeError, ValueError):
            return error_response(422, "invalid", "from_round 需要整数")
        engine = manager.engine_for(req.params["ws"])
        return json_response(engine.branch_conversation(
            session, from_round,
            mode=str(body.get("mode") or "redo"),
            summary=str(body.get("summary") or "mech"),
            focus=str(body.get("focus") or "")))

    # —— 会话管理（UI 重构 · 阶段 2.2）：重命名（PUT）/ 导出 ——
    # 2026-09-19 用户裁决：命名自由化——不限字符/不强制后缀；仅拒路径穿越与内部文件
    @_guard
    def h_session_title(req):
        """会话标题（用户裁决 2026-09-19）：LLM 总结首轮取名；缓存后直返。"""
        ws = manager.get_workspace(req.params["ws"])
        name = req.params.get("name", "")
        target = _session_path(ws, name)
        if target is None or not target.is_file():
            return error_response(404, "not_found", f"会话不存在：{name}")
        title = session_titles.load_titles(ws["path"]).get(name, "")
        if title == "":
            title = title_runner(target)
            if title != "":
                session_titles.save_title(ws["path"], name, title)
        return json_response({"name": name, "title": title})

    @_guard
    def h_session_rename(req):
        ws = manager.get_workspace(req.params["ws"])
        old_name = req.params.get("name", "")
        new_name = str(req.json().get("name", ""))
        src = _session_path(ws, old_name)
        dst = _session_path(ws, new_name)
        if src is None or dst is None:
            return error_response(422, "invalid", "会话名不合法")
        if not src.is_file():
            return error_response(404, "not_found", f"会话不存在：{old_name}")
        if dst.exists() and dst != src:
            return error_response(409, "conflict", "目标会话名已存在")
        src.rename(dst)
        return json_response({"name": dst.name})

    @_guard
    def h_session_export(req):
        ws = manager.get_workspace(req.params["ws"])
        name = req.params.get("name", "")
        src = _session_path(ws, name)
        if src is None or not src.is_file():
            return error_response(404, "not_found", f"会话不存在：{name}")
        fmt = (req.query.get("format") or "md").lower()
        rows = []
        for line in src.read_text(encoding="utf-8",
                                  errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
        if fmt == "json":
            content = json.dumps(rows, ensure_ascii=False, indent=1)
            filename = name[:-len(".jsonl")] + ".json"
        else:
            labels = {"user": "用户", "assistant": "助手", "system": "系统"}
            parts = []
            for r in rows:
                # 2026-10-01 壳端复验 P2：真实会话行为轮次格式
                # （round/user_text/artifacts/summary）；旧 role/content 行继续兼容。
                if str(r.get("type") or "") in ("branch", "compaction"):
                    continue  # 元数据行不导出（与聊天渲染同口径）
                if "user_text" in r or "summary" in r:
                    block = [f"## 第 {r.get('round', '?')} 轮", "",
                             f"**用户**：{r.get('user_text', '')}", ""]
                    # 结果：模型总体回复优先（pi 式）；无则机械 summary（Task A4）
                    answer = str(r.get("reply") or r.get("summary") or "")
                    if answer:
                        block += [f"**结果**：{answer}", ""]
                    # 产物：滤除 .wuxing/ 内部路径（F-* 中间产物不导出；Task A4）
                    arts = [str(a) for a in (r.get("artifacts") or [])
                            if not str(a).replace("\\", "/").startswith(".wuxing/")]
                    if arts:
                        block += ["**产物**：", *[f"- {a}" for a in arts], ""]
                    parts.append("\n".join(block))
                    continue
                role = labels.get(r.get("role"), r.get("role", ""))
                parts.append(f"## {role}\n\n{r.get('content', '')}\n")
            content = "\n".join(parts)
            filename = name[:-len(".jsonl")] + ".md"
        return json_response({"filename": filename, "content": content})

    server.add_route(
        "GET", r"^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/sessions$", h_sessions)
    server.add_route(
        "GET",
        r"^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/sessions/(?P<name>[^/]+)/rounds$",
        h_session_rounds)
    server.add_route(
        "GET",
        r"^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/unit-sessions/(?P<unit>[^/]+)$",
        h_unit_session)
    server.add_route(
        "POST",
        r"^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/conversations/branch$",
        h_conversations_branch)
    server.add_route(
        "GET", r"^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/trajectory$",
        h_trajectory)
    server.add_route(
        "POST",
        r"^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/sessions/(?P<name>[^/]+)/title$",
        h_session_title)
    server.add_route(
        "GET",
        r"^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/sessions/(?P<name>[^/]+)/export$",
        h_session_export)
    server.add_route(
        "PUT",
        r"^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/sessions/(?P<name>[^/]+)$",
        h_session_rename)
    server.add_route(
        "GET",
        r"^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/sessions/(?P<name>[^/]+)$",
        h_session)
