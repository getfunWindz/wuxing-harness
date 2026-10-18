"""TDD：P2 最小版（T6.2）——通知中心 / 智脑统计 / 评估报告查看。

设计 §10.2 缺口 11：三项均只读消费（壳不摸引擎内部）——
- 通知：壳事件日志（events.jsonl）过滤 + 未读计数（角标与列表同源）；
- 智脑：workdir/brain_memory.json 只读统计（默认关也收集，展示只读）；
- 报告：workdir/docs/*.md 列表（内容经既有 artifacts 路由只读读取）。
"""
import http.client
import json

from wuxing.shell.web.hub import EventHub


def _mk(tmp_path, hub=None):
    from wuxing.shell.web.api import register_api
    from wuxing.shell.web.manager import EngineManager
    from wuxing.shell.web.server import ShellServer
    hub = hub or EventHub(journal_path=tmp_path / "events.jsonl")
    mgr = EngineManager(hub=hub, state_path=tmp_path / "ws.json")
    srv = ShellServer(port=0, hub=hub)
    register_api(srv, mgr)
    port = srv.start()
    return srv, port, mgr, hub


def _get(port, path):
    c = http.client.HTTPConnection("127.0.0.60", port, timeout=5)
    c.request("GET", path)
    r = c.getresponse()
    data = r.read()
    status = r.status
    c.close()
    try:
        parsed = json.loads(data) if data else None
    except ValueError:
        parsed = data.decode("utf-8", "replace")   # 非 JSON（如报告文本）
    return status, parsed


def test_notifications_filter_unread_and_names(tmp_path):
    srv, port, mgr, hub = _mk(tmp_path)
    wd = tmp_path / "proj"
    wd.mkdir()
    ws = mgr.open_workspace(str(wd))
    try:
        hub.emit("task_submitted", workspace_id=ws["id"], run_id="r1")
        hub.emit("task_done", workspace_id=ws["id"], run_id="r1",
                 data={"status": "done"})
        hub.emit("unit_started", workspace_id=ws["id"], run_id="r1")   # 噪音
        hub.emit("safety_blocked", workspace_id=ws["id"], run_id="r1",
                 data={"tool": "bash", "command": "rm -rf /",
                       "reason": "危险命令"})
        hub.emit("task_done", workspace_id=ws["id"], run_id="r2",
                 data={"status": "failed"})
        hub.emit("task_cancelled", workspace_id=ws["id"], run_id="r3")
        status, data = _get(port, "/api/v1/notifications")
        assert status == 200, data
        items = data["items"]
        assert [i["type"] for i in items] == \
            ["task_cancelled", "task_done", "safety_blocked", "task_done"], items
        assert data["unread"] == 4
        assert data["last_seq"] == 6
        first = items[-1]
        assert first["status"] == "done" and first["level"] == "ok"
        assert first["workspace_name"] == "proj"
        blocked = items[2]
        assert blocked["level"] == "warn" and blocked["reason"] == "危险命令"
        failed = items[1]
        assert failed["status"] == "failed" and failed["level"] == "warn"
        # since = seq 4：列表仍为全量历史，仅未读数按 since 计
        status, data2 = _get(port, "/api/v1/notifications?since=4")
        assert status == 200 and data2["unread"] == 2, data2
        assert [i["seq"] for i in data2["items"]] == [6, 5, 4, 2]
    finally:
        srv.stop()


def test_notifications_excludes_pending_task_done(tmp_path):
    """待确认（task_done status=pending）不是通知——由工作区角标/确认门表达（审查 I6）。"""
    srv, port, mgr, hub = _mk(tmp_path)
    wd = tmp_path / "proj"
    wd.mkdir()
    ws = mgr.open_workspace(str(wd))
    try:
        hub.emit("task_done", workspace_id=ws["id"], run_id="r1",
                 data={"status": "pending"})
        hub.emit("task_done", workspace_id=ws["id"], run_id="r1",
                 data={"status": "done"})
        status, data = _get(port, "/api/v1/notifications")
        assert status == 200, data
        assert [i["status"] for i in data["items"]] == ["done"], data
        assert data["unread"] == 1
    finally:
        srv.stop()


def test_notifications_empty_and_invalid_since(tmp_path):
    srv, port, _mgr, _hub = _mk(tmp_path)
    try:
        status, data = _get(port, "/api/v1/notifications")
        assert status == 200 and data["items"] == []
        assert data["unread"] == 0 and data["last_seq"] == 0
        status, data = _get(port, "/api/v1/notifications?since=abc")
        assert status == 422, data
        # limit 钳制：超界回退默认（不报错）
        status, data = _get(port, "/api/v1/notifications?limit=9999")
        assert status == 200, data
    finally:
        srv.stop()


def test_brain_stats_readonly(tmp_path):
    srv, port, mgr, _hub = _mk(tmp_path)
    wd = tmp_path / "ws-brain"
    wd.mkdir()
    (wd / "brain_memory.json").write_text(json.dumps({"cases": [
        {"key": "k1", "domain": "execute", "model": "m", "success": True,
         "success_count": 3, "attempts": 4, "last_at": 100, "tier": "high"},
        {"key": "k2", "domain": "plan", "model": "m", "success": False,
         "success_count": 0, "attempts": 1, "last_at": 200, "tier": "low"},
        {"key": "k3", "domain": "plan", "model": "m", "success": True,
         "success_count": 1, "attempts": 1, "last_at": 300, "tier": "normal"},
    ]}, ensure_ascii=False), encoding="utf-8")
    ws = mgr.open_workspace(str(wd))
    try:
        status, data = _get(port, f"/api/v1/workspaces/{ws['id']}/brain")
        assert status == 200, data
        assert data["cases"] == 3 and data["attempts"] == 6
        assert data["success_count"] == 4
        assert abs(data["success_rate"] - 0.6667) < 0.001
        assert data["tiers"] == {"high": 1, "normal": 1, "low": 1}
        assert data["capacity"] == 500 and data["enabled"] is False
        assert [c["key"] for c in data["recent"]] == ["k3", "k2", "k1"]
        assert data["recent"][0]["success_rate"] == 1.0
    finally:
        srv.stop()


def test_brain_stats_missing_or_corrupt(tmp_path):
    srv, port, mgr, _hub = _mk(tmp_path)
    wd = tmp_path / "ws-empty"
    wd.mkdir()
    ws = mgr.open_workspace(str(wd))
    wd2 = tmp_path / "ws-corrupt"
    wd2.mkdir()
    (wd2 / "brain_memory.json").write_text("{ not json", encoding="utf-8")
    ws2 = mgr.open_workspace(str(wd2))
    try:
        for wid in (ws["id"], ws2["id"]):
            status, data = _get(port, f"/api/v1/workspaces/{wid}/brain")
            assert status == 200, data
            assert data["cases"] == 0 and data["recent"] == []
            assert data["tiers"] == {"high": 0, "normal": 0, "low": 0}
    finally:
        srv.stop()


def test_reports_lists_docs_markdown_only(tmp_path):
    srv, port, mgr, _hub = _mk(tmp_path)
    wd = tmp_path / "ws-docs"
    (wd / "docs").mkdir(parents=True)
    (wd / "docs" / "报告A.md").write_text("# A", encoding="utf-8")
    (wd / "docs" / "note.txt").write_text("no", encoding="utf-8")
    (wd / "docs" / "sub").mkdir()
    (wd / "docs" / "sub" / "deep.md").write_text("# deep", encoding="utf-8")
    (wd / "outside.md").write_text("# out", encoding="utf-8")
    ws = mgr.open_workspace(str(wd))
    try:
        status, data = _get(port, f"/api/v1/workspaces/{ws['id']}/reports")
        assert status == 200, data
        assert [r["name"] for r in data["reports"]] == ["报告A.md"]
        assert data["reports"][0]["path"] == "docs/报告A.md"
        assert data["reports"][0]["size"] == 3
        # 无 docs 目录 → 空表（不报错）
        wd2 = tmp_path / "ws-nodocs"
        wd2.mkdir()
        ws2 = mgr.open_workspace(str(wd2))
        status, data2 = _get(port, f"/api/v1/workspaces/{ws2['id']}/reports")
        assert status == 200 and data2["reports"] == []
        # 内容经既有 artifacts 路由只读读取（含中文文件名）
        from urllib.parse import quote
        status, body = _get(port, f"/api/v1/workspaces/{ws['id']}"
                                  f"/artifacts/docs/{quote('报告A.md')}")
        assert status == 200 and body == "# A", body
    finally:
        srv.stop()
