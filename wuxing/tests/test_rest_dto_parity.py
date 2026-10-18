"""REST DTO 对拍（P1a）：契约定义与实际服务响应互证。

契约源：wuxing/shell/web/contracts.py 的 REST_DTOS。
方法：启动带假引擎的真实服务（环回），逐个端点取响应并递归对拍
（未知键 → 失败；缺键 → 失败；类型不符 → 失败）。
"""
import dataclasses
import http.client
import json
import pathlib
import time
import types as pytypes
import typing

from wuxing.shell.web import contracts
from wuxing.shell.web.api import register_api
from wuxing.shell.web.hub import EventHub
from wuxing.shell.web.manager import EngineManager
from wuxing.shell.web.server import ShellServer


class UnitStarted:
    def __init__(self, unit_id, domain_id):
        self.unit_id, self.domain_id = unit_id, domain_id


class UnitDone:
    def __init__(self, unit_id, domain_id, status):
        self.unit_id, self.domain_id, self.status = unit_id, domain_id, status


class TaskDone:
    def __init__(self, status):
        self.status = status


class _Result:
    def __init__(self):
        self.status = "done"
        self.report = "报告"
        self.artifacts = []
        self.metrics = {"calls": 1}


class _FakeEngine:
    def __init__(self, workdir, auto_confirm=False):
        self.workdir, self.auto_confirm = workdir, auto_confirm

    def start_session(self, conversation_path=None):
        """修复①（2026-09-20）：manager 经引擎公开 API 建会话——测试桩用真实实现。"""
        from wuxing.conversation import ConversationState
        from wuxing.session_api import ConversationSession
        return ConversationSession(self, ConversationState(conversation_path))

    def run_task(self, text, on_event=None, references=None, conversation=None,
                 overrides=None):
        if on_event:
            on_event(UnitStarted("u1", "execute"))
            on_event(UnitDone("u1", "execute", "ok"))
            on_event(TaskDone("done"))
        return _Result()

    # ---- P2-M5（形状对齐真引擎：list/detail/install/remove/discover）----

    def list_skills(self):
        return [{"name": "find-skill", "description": "内置技能：检索与发现",
                 "level": "builtin", "enabled": True,
                 "model_invocable": True, "user_invocable": True,
                 "allowed_tools": []}]

    def skill_detail(self, name):
        if name != "find-skill":
            return None
        return {"name": "find-skill",
                "content": "---\nname: find-skill\n---\n",
                "scripts": {}, "builtin": True, "level": "builtin",
                "allowed_tools": [], "allowed_tools_missing": []}

    def install_skill(self, name, description, content, scripts=None):
        return {"ok": True, "name": str(name), "path": f"/tmp/skills/{name}"}

    def remove_skill(self, name):
        return {"ok": True, "name": str(name)}

    # ---- E2-UI：扩展命令（参数声明 + 运行）----

    def list_commands(self):
        return [{
            "name": "greet", "description": "问候", "source": "parity-ext",
            "args": [{"name": "who", "label": "对象", "type": "str",
                      "required": True, "default": None}],
        }]

    def run_command(self, name, args=None):
        if name != "greet":
            raise KeyError(f"未知扩展命令：{name}")
        return {"status": "ok",
                "text": f"你好，{(args or {}).get('who', '')}",
                "error": ""}

    def discover_skills(self, goal, constraints="", max_results=5):
        return {"ok": True, "items": [{"name": "demo-skill",
                                         "description": "演示发现"}]}

    def mcp_status(self):
        return {"enabled": True, "servers": [{
            "name": "demo-mcp", "command": "npx",
            "args": ["-y", "demo-mcp"],
            "tools": [{"name": "search", "permissions": {"read": True}}],
            "stats": {"connections": 1, "calls": 2},
        }]}

    def preview_session_context(self, conversation_path=None, unit_id=None):
        """B 期桩：形状对齐 ContextPreviewDto（真实投影由 test_context_preview/
        test_shell_context_api 覆盖）。"""
        return {
            "session": (pathlib.Path(conversation_path).name
                        if conversation_path else ""),
            "unit_id": "", "window": 200000, "est_tokens": 108,
            "percent": 0.0005,
            "band": "golden", "golden_pct": 0.2, "managed_pct": 0.5,
            "segments": [{"key": "history", "label": "会话历史",
                          "chars": 10, "est_tokens": 12,
                          "reference": False, "detail": "1 轮"}],
            "rounds": [{"round": 1, "summary": "", "chars": 10,
                         "est_tokens": 12, "omitted": True,
                         "replaced": False, "unit_marked": False,
                         "compacted": False}],
            "anchor_tokens": None, "anchor_ts": None, "anchor_unit": "",
            "unknown": [],
            "sources": {"history": True, "digest": True, "skills": True,
                        "prefix": True, "budget_tokens": 0},
            "messages": [],
            "budget_tokens": 0, "trimmed": [], "budget_auto": False,
            "available": True, "reason": "",
        }


def _check(dto_type, payload, path="response"):
    origin = typing.get_origin(dto_type)
    args = typing.get_args(dto_type)
    if origin in (typing.Union, pytypes.UnionType):
        non_none = [a for a in args if a is not type(None)]
        assert non_none, f"{path} 不支持的类型"
        if payload is None:
            assert len(non_none) != len(args), f"{path} 不应为 null"
            return
        last_err: AssertionError | None = None
        for cand in non_none:   # E2-UI：多候选逐一尝试（default 多类型联合）
            try:
                _check(cand, payload, path)
                return
            except AssertionError as exc:
                last_err = exc
        raise AssertionError(f"{path} 类型不符（{payload!r}）: {last_err}")
    if origin in (list, tuple):
        assert isinstance(payload, list), f"{path} 应为列表"
        for i, item in enumerate(payload):
            _check(args[0] if args else object, item, f"{path}[{i}]")
        return
    if dto_type is dict:
        assert isinstance(payload, dict), f"{path} 应为对象"
        return
    if dataclasses.is_dataclass(dto_type):
        assert isinstance(payload, dict), f"{path} 应为对象"
        hints = typing.get_type_hints(dto_type)
        for name in payload:
            assert name in hints, f"{path}.{name} 未在 {dto_type.__name__} 中定义"
        for name in hints:
            assert name in payload, f"{path}.{name} 缺失"
            _check(hints[name], payload[name], f"{path}.{name}")
        return
    if dto_type is bool:
        assert isinstance(payload, bool), f"{path} 应为布尔"
    elif dto_type in (int, float):
        assert isinstance(payload, (int, float)), f"{path} 应为数值"
    elif dto_type is str:
        assert isinstance(payload, str), f"{path} 应为字符串"
    else:
        assert payload is not None, f"{path} 不应为 null"


def _request(port, method, path, body=None):
    conn = http.client.HTTPConnection("127.0.0.60", port, timeout=10)
    headers = {}
    if method != "GET":
        headers["X-Wuxing"] = "1"
    payload = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        payload = json.dumps(body)
    conn.request(method, path, body=payload, headers=headers)
    resp = conn.getresponse()
    data = json.loads(resp.read().decode("utf-8"))
    conn.close()
    return resp.status, data


def test_rest_dtos_match_live_responses(tmp_path):
    hub = EventHub(journal_path=tmp_path / "events.jsonl")
    mgr = EngineManager(hub=hub,
                        engine_factory=lambda wd, ac: _FakeEngine(wd, ac),
                        state_path=tmp_path / "ws.json")
    srv = ShellServer(port=0, hub=hub)
    register_api(srv, mgr, dialog_runner=lambda kind: ["/tmp/ref.md"])
    port = srv.start()
    try:
        ws_id = mgr.open_workspace(str(tmp_path))["id"]

        st, health = _request(port, "GET", "/health")
        assert st == 200
        _check(contracts.HealthDto, health)

        st, about = _request(port, "GET", "/api/v1/about")
        assert st == 200
        _check(contracts.AboutDto, about)

        st, listing = _request(port, "GET", "/api/v1/workspaces")
        assert st == 200
        _check(contracts.WorkspaceListDto, listing)

        st, snapshot = _request(
            port, "GET", f"/api/v1/workspaces/{ws_id}/snapshot")
        assert st == 200
        _check(contracts.SnapshotDto, snapshot)

        st, submitted = _request(
            port, "POST", f"/api/v1/workspaces/{ws_id}/tasks",
            {"text": "DTO 对拍"})
        assert st == 202
        _check(contracts.SubmitDto, submitted)

        deadline = time.time() + 5
        while time.time() < deadline:
            _, snapshot = _request(
                port, "GET", f"/api/v1/workspaces/{ws_id}/snapshot")
            if snapshot.get("result"):
                break
            time.sleep(0.1)
        _check(contracts.SnapshotDto, snapshot)
        assert snapshot["result"]["status"] == "done"

        # ---- P2-M4：观测面 DTO 对拍（先造数据再取响应） ----
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "报告.md").write_text("# 报告\n", encoding="utf-8")
        wuxing_dir = tmp_path / ".wuxing"
        wuxing_dir.mkdir(exist_ok=True)
        (wuxing_dir / "provenance.jsonl").write_text(json.dumps({
            "provenance_id": "a1", "unit_id": "u1", "parent_id": "",
            "task_hash": "h", "goal": "g", "domain": "execute",
            "model": "mock", "status": "ok", "artifacts": [],
            "ts": 1.0,
        }) + "\n", encoding="utf-8")
        (wuxing_dir / "trace.jsonl").write_text(json.dumps({
            "ts": 1.0, "event": "unit_start", "unit_id": "u1",
            "domain": "execute", "extra": 1,
        }) + "\n", encoding="utf-8")
        (tmp_path / "brain_memory.json").write_text(json.dumps({
            "cases": [{
                "key": "k", "domain": "execute", "model": "mock",
                "tier": "high", "attempts": 2, "success_count": 2,
                "last_at": 1.0,
            }],
        }), encoding="utf-8")

        st, hist = _request(
            port, "GET", f"/api/v1/workspaces/{ws_id}/tasks/history")
        assert st == 200
        _check(contracts.TaskHistoryDto, hist)
        assert hist["history"], "任务历史应有本次运行记录"

        st, notices = _request(
            port, "GET", "/api/v1/notifications?since=0&limit=100")
        assert st == 200
        _check(contracts.NotificationListDto, notices)
        assert notices["items"], "任务完成后应有通知项"

        st, brain = _request(
            port, "GET", f"/api/v1/workspaces/{ws_id}/brain")
        assert st == 200
        _check(contracts.BrainStatsDto, brain)
        assert brain["cases"] == 1

        st, reports = _request(
            port, "GET", f"/api/v1/workspaces/{ws_id}/reports")
        assert st == 200
        _check(contracts.ReportListDto, reports)
        assert reports["reports"], "docs/*.md 应被收录"

        st, prov = _request(
            port, "GET", f"/api/v1/workspaces/{ws_id}/observe/provenance")
        assert st == 200
        _check(contracts.ProvenanceListDto, prov)
        assert prov["rows"]

        st, trace = _request(
            port, "GET", f"/api/v1/workspaces/{ws_id}/observe/trace")
        assert st == 200
        _check(contracts.TraceListDto, trace)
        assert trace["rows"]

        st, elog = _request(port, "GET", "/api/v1/events/log?tail=50")
        assert st == 200
        _check(contracts.EventLogDto, elog)
        assert elog["rows"]

        # ---- P2-M5：管理面 DTO 对拍（技能/MCP） ----
        st, skills = _request(port, "GET", "/api/v1/skills")
        assert st == 200
        _check(contracts.SkillListDto, skills)
        assert skills["skills"]

        st, detail = _request(port, "GET", "/api/v1/skills/find-skill")
        assert st == 200
        _check(contracts.SkillDetailDto, detail)
        assert detail["builtin"] is True

        st, installed = _request(port, "POST", "/api/v1/skills/install",
                                 {"name": "demo", "description": "d",
                                  "content": "---\n---\n"})
        assert st == 200
        _check(contracts.SkillInstallDto, installed)

        st, removed = _request(port, "DELETE", "/api/v1/skills/demo")
        assert st == 200
        _check(contracts.SkillRemoveDto, removed)

        st, discovered = _request(port, "POST", "/api/v1/skills/discover",
                                  {"goal": "测试"})
        assert st == 200
        _check(contracts.SkillDiscoverDto, discovered)

        st, mcp = _request(port, "GET", "/api/v1/mcp")
        assert st == 200
        _check(contracts.McpStatusDto, mcp)
        assert mcp["servers"][0]["args"]

        st, reloaded = _request(port, "POST", "/api/v1/mcp/reload")
        assert st == 200
        _check(contracts.McpReloadDto, reloaded)

        # ---- B 期（2026-09-22）：上下文投影 DTO 对拍 ----
        st, previews = _request(
            port, "GET", f"/api/v1/workspaces/{ws_id}/context-previews")
        assert st == 200
        _check(contracts.ContextPreviewListDto, previews)
        assert previews["items"], "提交过任务 → 应有会话行"
        name = previews["items"][0]["session"]

        st, cpreview = _request(
            port, "GET",
            f"/api/v1/workspaces/{ws_id}/context-preview?session={name}")
        assert st == 200
        _check(contracts.ContextPreviewDto, cpreview)
        assert cpreview["available"] is True

        st, edited = _request(
            port, "POST",
            f"/api/v1/workspaces/{ws_id}/conversations/{name}/context-edits",
            {"round": 1, "op": "omit"})
        assert st == 200
        _check(contracts.ContextEditDto, edited)

        st, sources = _request(
            port, "GET",
            f"/api/v1/workspaces/{ws_id}/context-sources?session={name}")
        assert st == 200
        _check(contracts.ContextSourcesAckDto, sources)
        assert sources["sources"]["history"] is True

        st, saved = _request(
            port, "PUT",
            f"/api/v1/workspaces/{ws_id}/context-sources?session={name}",
            {"history": False, "budget_tokens": 8000})
        assert st == 200
        _check(contracts.ContextSourcesAckDto, saved)
        assert saved["sources"]["history"] is False
        assert saved["sources"]["budget_tokens"] == 8000

        # ---- P2-M6：主视图面 DTO 对拍（搜索/系统对话框桥） ----
        st, searched = _request(port, "GET", "/api/v1/search?q=DTO")
        assert st == 200
        _check(contracts.SearchResultDto, searched)
        assert searched["tasks"], "搜索应命中已跑任务"

        st, picked = _request(port, "POST", "/api/v1/dialog/pick",
                              {"kind": "files"})
        assert st == 200
        _check(contracts.DialogPickDto, picked)

        # ---- E2-UI：扩展命令/装配预设 DTO 对拍 ----
        st, cmdlist = _request(
            port, "GET", f"/api/v1/workspaces/{ws_id}/extensions/commands")
        assert st == 200
        _check(contracts.ExtCommandListDto, cmdlist)
        assert cmdlist["commands"], "应有扩展命令"
        arg = cmdlist["commands"][0]["args"][0]
        assert arg["name"] == "who" and arg["default"] is None

        st, cmdrun = _request(
            port, "POST",
            f"/api/v1/workspaces/{ws_id}/extensions/commands/greet",
            {"args": {"who": "DTO"}})
        assert st == 200
        _check(contracts.ExtCommandRunDto, cmdrun)
        assert cmdrun["status"] == "ok"

        st, presetlist = _request(
            port, "GET", f"/api/v1/workspaces/{ws_id}/presets")
        assert st == 200
        _check(contracts.AssemblyPresetListDto, presetlist)
        lean = next(p for p in presetlist["presets"] if p["name"] == "lean")
        assert lean["chain"] == ["lean", "standard"] and lean["hash"]
        assert lean["error"] == ""

        st, spget = _request(
            port, "GET",
            f"/api/v1/workspaces/{ws_id}/session-preset?session=dto.jsonl")
        assert st == 200
        _check(contracts.SessionPresetDto, spget)
        assert spget["name"] == ""

        st, spput = _request(
            port, "PUT", f"/api/v1/workspaces/{ws_id}/session-preset",
            {"session": "dto.jsonl", "name": "lean"})
        assert st == 200
        _check(contracts.SessionPresetDto, spput)
        assert spput["name"] == "lean"
        assert picked["paths"]
    finally:
        srv.stop()
        mgr.shutdown()
