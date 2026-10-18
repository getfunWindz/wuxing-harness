"""上下文投影/来源/模式/设计态/编辑路由（Q1：自 api.py 逐字迁移）。"""
import json
import pathlib
import time

from wuxing.shell.web.server import error_response, json_response

from .base import _INTERNAL_JSONL, _guard


def _append_jsonl(base_dir, record: dict, name: str = "context-edits.jsonl") -> None:
    """追加一行 JSONL（3 次重试；失败静默——编辑是投影层设施，不是生命线）。"""
    target = pathlib.Path(base_dir) / name
    line = json.dumps(record, ensure_ascii=False) + "\n"
    for attempt in range(3):
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("a", encoding="utf-8") as f:
                f.write(line)
            return
        except OSError:
            time.sleep(0.02 * (attempt + 1))


def _spec_dto(wd, st):
    """设计态 → SpecDto（无 spec_slug → None；文件在场性读侧判定）。"""
    slug = str(st.get("spec_slug") or "")
    if not slug:
        return None
    from wuxing import spec_doc
    try:
        ready = spec_doc.spec_path(wd, slug).is_file()
    except ValueError:
        ready = False
    return {"slug": slug,
            "path": str(st.get("spec_path") or f".wuxing/specs/{slug}.md"),
            "hash": str(st.get("spec_hash") or ""),
            "ready": ready}


def register(server, ctx) -> None:
    manager = ctx.manager

    # —— 上下文投影/编辑（B 期 · 2026-09-22）：预览 / 列表 / 追加编辑 ——
    @_guard
    def h_context_preview(req):
        ws = manager.get_workspace(req.params["ws"])
        session = (req.query.get("session") or "").strip()
        unit = (req.query.get("unit") or "").strip()
        if not session and not unit:
            return error_response(422, "invalid", "需要 session 或 unit 参数")
        engine = manager.engine_for(req.params["ws"])
        if unit:
            return json_response(engine.preview_session_context(unit_id=unit))
        if "/" in session or "\\" in session or session in _INTERNAL_JSONL:
            return error_response(422, "invalid", f"非法会话名：{session}")
        target = pathlib.Path(ws["path"]) / ".wuxing" / session
        return json_response(engine.preview_session_context(
            conversation_path=target))

    @_guard
    def h_context_previews(req):
        ws = manager.get_workspace(req.params["ws"])
        base = pathlib.Path(ws["path"]) / ".wuxing"
        engine = manager.engine_for(req.params["ws"])
        items: list[dict] = []
        if base.is_dir():
            for p in sorted(base.glob("*.jsonl")):
                if not p.is_file() or p.name in _INTERNAL_JSONL:
                    continue
                d = engine.preview_session_context(conversation_path=p)
                items.append({"session": d["session"], "window": d["window"],
                              "est_tokens": d["est_tokens"],
                              "percent": d["percent"],
                              "available": d["available"]})
        return json_response({"items": items})

    @_guard
    def h_context_sources(req):
        """A 期（2026-09-22）：会话级来源开关读取（GET）/写入（PUT）。"""
        ws = manager.get_workspace(req.params["ws"])
        session = (req.query.get("session") or "").strip()
        unit = (req.query.get("unit") or "").strip()
        if not session and not unit:
            return error_response(422, "invalid", "需要 session 或 unit 参数")
        if "/" in session or "\\" in session or session in _INTERNAL_JSONL:
            return error_response(422, "invalid", f"非法会话名：{session}")
        from wuxing.context_sources import resolve as _resolve_sources
        from wuxing.context_sources import save as _save_sources
        engine = manager.engine_for(req.params["ws"])
        _cfg = getattr(engine, "cfg", None)
        default_budget = int(getattr(_cfg, "context_budget_tokens", 0) or 0) \
            if _cfg is not None else 0
        scope, key = ("units", unit) if unit else ("conversations", session)
        if req.method == "PUT":
            body = req.json()
            allowed = {"history", "digest", "skills", "prefix", "budget_tokens"}
            unknown = sorted(k for k in body if k not in allowed)
            if unknown:
                return error_response(422, "invalid", f"未知键：{unknown}")
            if "budget_tokens" in body:
                try:
                    b = int(body["budget_tokens"])
                except (TypeError, ValueError):
                    return error_response(422, "invalid", "budget_tokens 必须为整数")
                if b < 0:
                    return error_response(422, "invalid", "budget_tokens 不得为负")
            _save_sources(ws["path"], scope, key, body)
        sources = _resolve_sources(
            ws["path"], conversation=session if not unit else "",
            unit=unit, default_budget=default_budget)
        preview = (engine.preview_session_context(unit_id=unit) if unit else
                   engine.preview_session_context(
                       conversation_path=pathlib.Path(ws["path"]) / ".wuxing" / session))
        return json_response({"ok": True, "sources": sources, "preview": preview})

    @_guard
    def h_session_modes(req):
        """双模式批 1：会话级模式读取（GET）/写入（PUT——仅空白会话可切）。"""
        ws = manager.get_workspace(req.params["ws"])
        session = (req.query.get("session") or "").strip()
        if not session:
            return error_response(422, "invalid", "需要 session 参数")
        if "/" in session or "\\" in session or session in _INTERNAL_JSONL:
            return error_response(422, "invalid", f"非法会话名：{session}")
        from wuxing.session_modes import conversation_is_blank
        from wuxing.session_modes import resolve as _resolve_mode
        from wuxing.session_modes import save as _save_mode
        engine = manager.engine_for(req.params["ws"])
        _cfg = getattr(engine, "cfg", None)
        default_id = str(getattr(_cfg, "mode_default", "")
                         or "minimal-standard")
        picker = bool(getattr(_cfg, "mode_picker_enabled", True))
        conv_path = pathlib.Path(ws["path"]) / ".wuxing" / session
        if req.method == "PUT":
            body = req.json()
            unknown = sorted(k for k in body if k not in ("mode", "variant"))
            if unknown:
                return error_response(422, "invalid", f"未知键：{unknown}")
            # 空白判据（机制守卫——非空白会话拒绝切换，设计 §8）
            if not conversation_is_blank(conv_path):
                return error_response(422, "session/not-blank",
                                      "会话非空白——模式仅可在空白会话切换")
            try:
                _save_mode(ws["path"], session,
                           str(body.get("mode") or ""),
                           str(body.get("variant") or ""))
            except ValueError as e:
                return error_response(422, "invalid", str(e))
        r = _resolve_mode(ws["path"], conversation=session, default=default_id)
        return json_response({
            "mode": r["mode"], "variant": r["variant"],
            "source": r["source"],
            "editable": conversation_is_blank(conv_path),
            "picker_enabled": picker, "default_mode": default_id})

    @_guard
    def h_design_state(req):
        """双模式批 3（循迹）：设计态读取（GET）/交接（PUT phase=ready）。"""
        ws = manager.get_workspace(req.params["ws"])
        session = (req.query.get("session") or "").strip()
        if not session:
            return error_response(422, "invalid", "需要 session 参数")
        if "/" in session or "\\" in session or session in _INTERNAL_JSONL:
            return error_response(422, "invalid", f"非法会话名：{session}")
        from wuxing import design_state as _ds
        from wuxing.map_doc import file_hash, is_usable, map_path
        wd = ws["path"]
        if req.method == "PUT":
            body = req.json()
            unknown = sorted(k for k in body if k not in ("phase",))
            if unknown:
                return error_response(422, "invalid", f"未知键：{unknown}")
            phase = str(body.get("phase") or "")
            if phase != "ready":
                return error_response(422, "invalid",
                                      "仅支持 phase=ready（交给执行）")
            _ds.save(wd, {"session": session, "phase": "ready"})
        st = _ds.load(wd)
        cur_hash = file_hash(map_path(wd))
        stored = str(st.get("map_hash") or "")
        return json_response({
            "session": session,
            "phase": str(st.get("phase") or ""),
            "round": int(st.get("round") or 0),
            "questions": [{"q": str(q.get("q") or ""),
                           "recommend": str(q.get("recommend") or "")}
                          for q in (st.get("questions") or [])
                          if isinstance(q, dict)],
            "tickets": [{
                "id": str(t.get("id") or ""),
                "statement": str(t.get("statement") or ""),
                "recommend": str(t.get("recommend") or ""),
                "blocked_by": [str(x) for x in (t.get("blocked_by") or [])],
                "status": str(t.get("status") or "open"),
                "resolution": str(t.get("resolution") or ""),
                "frontier": str(t.get("id") or "") in _ds.frontier_ids(st),
            } for t in _ds.tickets(st)],
            "facts": [str(f) for f in (st.get("facts") or [])],
            "drift": [{"round": int(d.get("round") or 0),
                       "kind": str(d.get("kind") or ""),
                       "id": str(d.get("id") or ""),
                       "detail": str(d.get("detail") or ""),
                       "ts": float(d.get("ts") or 0.0)}
                      for d in (st.get("drift") or []) if isinstance(d, dict)],
            "map_path": str(st.get("map_path") or "WUXING.md"),
            "map_hash": stored,
            "map_changed": bool(stored and is_usable(wd) and cur_hash != stored),
            "map_ready": is_usable(wd),
            "available": bool(st),
            "spec": _spec_dto(wd, st)})

    @_guard
    def h_unit_context_edit(req):
        """A2：碎片消息三键编辑（append-only；投影层生效；日志零改写）。"""
        ws = manager.get_workspace(req.params["ws"])
        unit = str(req.params.get("unit", ""))
        if unit == "" or "/" in unit or "\\" in unit:
            return error_response(422, "invalid", f"非法碎片名：{unit}")
        body = req.json()
        op = str(body.get("op") or "")
        if op not in ("omit", "replace", "restore"):
            return error_response(422, "invalid",
                                  "op 必须为 omit/replace/restore")
        try:
            idx = int(body.get("index"))
        except (TypeError, ValueError):
            return error_response(422, "invalid", "index 必须为整数")
        content = str(body.get("content") or "")
        if op == "replace" and content == "":
            return error_response(422, "invalid", "replace 必须携带 content")
        rec = {"kind": "unit", "unit": unit,
               "file": str(body.get("file") or ""), "index": idx,
               "fp_in": str(body.get("fp_in") or ""),
               "fp_out": str(body.get("fp_out") or ""),
               "op": op, "ts": round(time.time(), 3)}
        if op == "replace":
            rec["content"] = content
        _append_jsonl(pathlib.Path(ws["path"]) / ".wuxing", rec)
        engine = manager.engine_for(req.params["ws"])
        return json_response({
            "ok": True,
            "preview": engine.preview_session_context(unit_id=unit)})

    @_guard
    def h_context_edit(req):
        """追加一条投影层编辑（append-only；日志零改写；投影立即生效）。"""
        ws = manager.get_workspace(req.params["ws"])
        name = str(req.params.get("name", ""))
        if (name == "" or "/" in name or "\\" in name
                or name in _INTERNAL_JSONL):
            return error_response(422, "invalid", f"非法会话名：{name}")
        if not name.endswith(".jsonl"):
            name = name + ".jsonl"
        body = req.json()
        op = str(body.get("op") or "")
        if op not in ("omit", "replace", "restore"):
            return error_response(422, "invalid",
                                  "op 必须为 omit/replace/restore")
        try:
            rnd = int(body.get("round"))
        except (TypeError, ValueError):
            return error_response(422, "invalid", "round 必须为整数")
        content = str(body.get("content") or "")
        if op == "replace" and content == "":
            return error_response(422, "invalid", "replace 必须携带 content")
        rec = {"conversation": name, "round": rnd, "op": op,
               "ts": round(time.time(), 3)}
        if op == "replace":
            rec["content"] = content
        _append_jsonl(base_dir=pathlib.Path(ws["path"]) / ".wuxing",
                      record=rec)
        engine = manager.engine_for(req.params["ws"])
        preview = engine.preview_session_context(
            conversation_path=pathlib.Path(ws["path"]) / ".wuxing" / name)
        return json_response({"ok": True, "preview": preview})

    server.add_route(
        "GET", r"^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/context-preview$",
        h_context_preview)
    server.add_route(
        "GET", r"^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/context-previews$",
        h_context_previews)
    server.add_route(
        "GET", r"^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/context-sources$",
        h_context_sources)
    server.add_route(
        "PUT", r"^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/context-sources$",
        h_context_sources)
    server.add_route(
        "GET", r"^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/session-modes$",
        h_session_modes)
    server.add_route(
        "PUT", r"^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/session-modes$",
        h_session_modes)
    server.add_route(
        "GET", r"^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/design-state$",
        h_design_state)
    server.add_route(
        "PUT", r"^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/design-state$",
        h_design_state)
    server.add_route(
        "POST",
        r"^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/unit-sessions/(?P<unit>[^/]+)"
        r"/context-edits$", h_unit_context_edit)
    server.add_route(
        "POST",
        r"^/api/v1/workspaces/(?P<ws>[0-9a-f]+)/conversations/(?P<name>[^/]+)"
        r"/context-edits$", h_context_edit)
