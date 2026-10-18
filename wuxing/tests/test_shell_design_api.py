"""TDD（双模式批 3 · Task 4）：设计态/地图端点（GET/PUT + 恢复字段 + 校验）。"""
import http.client
import json

from wuxing.shell.web.hub import EventHub


def _mk_server(tmp_path):
    from wuxing.shell.web.api import register_api
    from wuxing.shell.web.manager import EngineManager
    from wuxing.shell.web.server import ShellServer
    hub = EventHub()
    mgr = EngineManager(hub=hub, state_path=tmp_path / "ws.json")
    srv = ShellServer(port=0, hub=hub)
    register_api(srv, mgr)
    port = srv.start()
    return srv, port, mgr


def _request(port, method, path, body=None):
    c = http.client.HTTPConnection("127.0.0.60", port, timeout=10)
    headers = {}
    if method != "GET":
        headers["X-Wuxing"] = "1"
        headers["Content-Type"] = "application/json"
    c.request(method, path,
              body=json.dumps(body) if body is not None else None,
              headers=headers)
    r = c.getresponse()
    data = r.read()
    status = r.status
    c.close()
    return status, data


def _open(tmp_path, mgr, name="proj"):
    wd = tmp_path / name
    wd.mkdir()
    (wd / ".wuxing").mkdir()
    return mgr.open_workspace(str(wd)), wd


def test_design_state_get_and_handoff(tmp_path):
    srv, port, mgr = _mk_server(tmp_path)
    ws, wd = _open(tmp_path, mgr)
    base = f"/api/v1/workspaces/{ws['id']}"
    try:
        # 无设计态 → available False（不造假）
        status, data = _request(
            port, "GET", f"{base}/design-state?session=conversation-w.jsonl")
        assert status == 200, data
        d = json.loads(data)
        assert d["available"] is False and d["phase"] == ""
        # 写真实设计态 → GET 全字段
        from wuxing.design_state import save
        save(wd, {"session": "conversation-w.jsonl", "phase": "grilling",
                  "round": 2,
                  "questions": [{"q": "范围？", "recommend": "最小可用"}],
                  "facts": ["仅 docs/"], "map_path": "WUXING.md",
                  "map_hash": ""})
        status, data = _request(
            port, "GET", f"{base}/design-state?session=conversation-w.jsonl")
        d2 = json.loads(data)
        assert d2["available"] is True and d2["phase"] == "grilling"
        assert d2["round"] == 2 and d2["questions"][0]["q"] == "范围？"
        assert d2["questions"][0]["recommend"] == "最小可用"
        assert d2["facts"] == ["仅 docs/"] and d2["map_ready"] is False
        # 「交给执行」：PUT phase=ready
        status, data = _request(
            port, "PUT", f"{base}/design-state?session=conversation-w.jsonl",
            {"phase": "ready"})
        assert status == 200, data
        assert json.loads(data)["phase"] == "ready"
        # 非法 phase → 422
        status, data = _request(
            port, "PUT", f"{base}/design-state?session=conversation-w.jsonl",
            {"phase": "bogus"})
        assert status == 422 and json.loads(data)["error"]["code"] == "invalid"
        status, _ = _request(port, "GET", f"{base}/design-state")
        assert status == 422
    finally:
        srv.stop()


def test_design_state_map_changed_flag(tmp_path):
    srv, port, mgr = _mk_server(tmp_path)
    ws, wd = _open(tmp_path, mgr)
    base = f"/api/v1/workspaces/{ws['id']}"
    try:
        from wuxing import design_state
        from wuxing.map_doc import file_hash, map_path, write_sections
        write_sections(wd, destination="目标 A", route="- [ ] 步骤")
        design_state.save(wd, {"session": "c1.jsonl", "phase": "map",
                               "map_path": "WUXING.md",
                               "map_hash": file_hash(map_path(wd))})
        _status, data = _request(
            port, "GET", f"{base}/design-state?session=c1.jsonl")
        d = json.loads(data)
        assert d["map_ready"] is True and d["map_changed"] is False
        # 外部编辑地图 → map_changed True（不静默覆盖）
        write_sections(wd, destination="目标 A 改")
        _status, data = _request(
            port, "GET", f"{base}/design-state?session=c1.jsonl")
        assert json.loads(data)["map_changed"] is True
    finally:
        srv.stop()


def test_map_endpoint(tmp_path):
    srv, port, mgr = _mk_server(tmp_path)
    ws, wd = _open(tmp_path, mgr)
    base = f"/api/v1/workspaces/{ws['id']}"
    try:
        status, data = _request(port, "GET", f"{base}/map")
        d = json.loads(data)
        assert status == 200 and d["available"] is False
        from wuxing.map_doc import write_sections
        write_sections(wd, project="演示", destination="发布 v1",
                       route="- [ ] 实现核心\n- [x] 建仓库",
                       decisions="2026-09-24 · 选择 A · 理由 · 来源",
                       fog="部署方式未定", out_of_scope="移动端不做")
        status, data = _request(port, "GET", f"{base}/map")
        d2 = json.loads(data)
        assert d2["available"] is True and d2["project"] == "演示"
        assert d2["destination"] == "发布 v1"
        assert d2["route"][0].startswith("- [ ] 实现核心")
        assert d2["decisions"] and d2["fog"] == ["部署方式未定"]
        assert len(d2["hash"]) == 64
    finally:
        srv.stop()


def test_design_state_exposes_tickets_with_frontier(tmp_path):
    srv, port, mgr = _mk_server(tmp_path)
    ws, wd = _open(tmp_path, mgr)
    base = f"/api/v1/workspaces/{ws['id']}"
    try:
        from wuxing.design_state import save
        save(wd, {"session": "conversation-w.jsonl", "phase": "grilling",
                  "round": 1, "next_ticket": 3, "branch_head": "D-1",
                  "decision_tickets": [
                      {"id": "Q-1", "statement": "A", "recommend": "a",
                       "blocked_by": [], "status": "open"},
                      {"id": "Q-2", "statement": "B", "recommend": "",
                       "blocked_by": ["Q-1"], "status": "open"}]})
        status, data = _request(
            port, "GET", f"{base}/design-state?session=conversation-w.jsonl")
        d = json.loads(data)
        assert status == 200
        assert [t["id"] for t in d["tickets"]] == ["Q-1", "Q-2"]
        assert d["tickets"][0]["frontier"] is True
        assert d["tickets"][1]["frontier"] is False
    finally:
        srv.stop()


def test_design_state_exposes_spec(tmp_path):
    srv, port, mgr = _mk_server(tmp_path)
    ws, wd = _open(tmp_path, mgr)
    base = f"/api/v1/workspaces/{ws['id']}"
    try:
        _status, data = _request(
            port, "GET", f"{base}/design-state?session=c1.jsonl")
        assert json.loads(data)["spec"] is None
        from wuxing import design_state, spec_doc
        e = spec_doc.write(wd, title="规格A", slug="s-a",
                           sections={"problem": "p"})
        design_state.save(wd, {"session": "c1.jsonl", "spec_slug": e["slug"],
                               "spec_path": ".wuxing/specs/s-a.md",
                               "spec_hash": e["hash"]})
        _status, data = _request(
            port, "GET", f"{base}/design-state?session=c1.jsonl")
        sp = json.loads(data)["spec"]
        assert sp["slug"] == "s-a" and sp["ready"] is True
        assert sp["path"] == ".wuxing/specs/s-a.md"
        assert len(sp["hash"]) == 64
    finally:
        srv.stop()


def test_tickets_endpoints_propose_publish(tmp_path):
    srv, port, mgr = _mk_server(tmp_path)
    ws, wd = _open(tmp_path, mgr)
    base = f"/api/v1/workspaces/{ws['id']}"
    try:
        _status, data = _request(port, "GET", f"{base}/tickets")
        d = json.loads(data)
        assert d["tickets"] == [] and d["spec"] == ""
        from wuxing import tickets as _t
        _t.create(wd, title="切片一", goal="A", acceptance=["A 可用"], spec="s-1")
        _status, data = _request(port, "GET", f"{base}/tickets")
        d = json.loads(data)
        assert d["tickets"][0]["id"] == "T-1"
        assert d["tickets"][0]["status"] == "proposed"
        # 发布（用户动作）
        status, data = _request(port, "POST", f"{base}/tickets/publish", {})
        d = json.loads(data)
        assert status == 200 and d["tickets"][0]["status"] == "ready"
        # 审查 F2：显式发布非 proposed（已 ready）→ 422（不重置状态机）
        status, _d = _request(port, "POST", f"{base}/tickets/publish",
                              {"ids": ["T-1"]})
        assert status == 422
        # 环 → 422（可见，不静默）
        t3 = _t.create(wd, title="D")
        t4 = _t.create(wd, title="E", deps=[t3["id"]])
        _t._append(wd, {"event": "updated", "id": t3["id"],
                        "patch": {"deps": [t4["id"]]}, "ts": 1.0})
        status, _d = _request(port, "POST", f"{base}/tickets/publish", {})
        assert status == 422
    finally:
        srv.stop()


def test_tickets_reset_endpoint(tmp_path):
    """W4.5：票据重置端点——失败票重跑 + 依赖闭包；非法输入 422。"""
    srv, port, mgr = _mk_server(tmp_path)
    ws, wd = _open(tmp_path, mgr)
    base = f"/api/v1/workspaces/{ws['id']}"
    try:
        from wuxing import tickets as _t
        t1 = _t.create(wd, title="切片一", goal="A")
        t2 = _t.create(wd, title="切片二", goal="B", deps=[t1["id"]])
        _t.publish(wd)
        _t.update(wd, t1["id"], {"status": "done"})
        _t.update(wd, t2["id"], {"status": "failed"})
        status, data = _request(port, "POST", f"{base}/tickets/reset",
                                {"ids": [t2["id"]]})
        d = json.loads(data)
        assert status == 200
        st = {t["id"]: t["status"] for t in d["tickets"]}
        assert st == {"T-1": "done", "T-2": "ready"}
        # 缺省：全部 failed/cancelled（本用例无其他失败票 → 幂等）
        status, _d = _request(port, "POST", f"{base}/tickets/reset", {})
        assert status == 200
        # 未知 id / running → 422（可见拒绝）
        status, _d = _request(port, "POST", f"{base}/tickets/reset",
                              {"ids": ["T-99"]})
        assert status == 422
        _t.update(wd, t1["id"], {"status": "running"})
        status, _d = _request(port, "POST", f"{base}/tickets/reset",
                              {"ids": [t1["id"]]})
        assert status == 422
    finally:
        srv.stop()


def test_map_view_decisions_structured(tmp_path):
    srv, port, mgr = _mk_server(tmp_path)
    ws, wd = _open(tmp_path, mgr)
    try:
        from wuxing.map_doc import append_decision
        append_decision(wd, text="采用 A", why="稳", source="Q-1")
        status, data = _request(
            port, "GET", f"/api/v1/workspaces/{ws['id']}/map")
        d = json.loads(data)
        assert status == 200
        assert d["decisions"][0]["id"] == "D-1"
        assert d["decisions"][0]["text"] == "采用 A"
    finally:
        srv.stop()


def test_design_state_exposes_drift(tmp_path):
    """C5：设计态端点返回 drift（机械校验可见面）。"""
    srv, port, mgr = _mk_server(tmp_path)
    ws, wd = _open(tmp_path, mgr)
    base = f"/api/v1/workspaces/{ws['id']}"
    try:
        from wuxing.design_state import save
        save(wd, {"session": "conversation-w.jsonl", "phase": "grilling",
                  "round": 2, "drift": [
                      {"round": 2, "kind": "unknown-ticket", "id": "Q-9",
                       "detail": "决策引用了未打开票据", "ts": 1.0}]})
        status, data = _request(
            port, "GET", f"{base}/design-state?session=conversation-w.jsonl")
        d = json.loads(data)
        assert status == 200, data
        assert d["drift"][0]["kind"] == "unknown-ticket"
        assert d["drift"][0]["id"] == "Q-9"
    finally:
        srv.stop()
