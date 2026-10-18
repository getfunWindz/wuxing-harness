"""TDD：技能/MCP 管理面端点（壳 UI 阶段 5 · T5.1/T5.2）。

- 技能：清单 / 详情 / 安装 / 卸载 / 在线发现（经引擎公开契约）
- MCP：状态（服务/工具/权限/连接统计）/ 重载
- 无工作区时 → 404（管理面需引擎实例）
"""
import http.client
import json

from wuxing.shell.web.hub import EventHub


class _FakeEngine:
    """最小管理面引擎（只实现契约方法）。"""

    def __init__(self, workdir, auto_confirm=False):
        self.workdir = workdir

    def list_skills(self):
        return [{"name": "demo", "description": "演示", "level": "fragment",
                 "enabled": True}]

    def skill_detail(self, name):
        if name != "demo":
            return None
        return {"name": "demo", "content": "---\nname: demo\n---\n正文",
                "scripts": []}

    def install_skill(self, name, description, content, scripts=None):
        return {"ok": True, "name": name, "path": f"user_skills/{name}"}

    def remove_skill(self, name):
        if name == "builtin-x":
            raise ValueError("内置技能不可卸载")
        return {"ok": True, "name": name}

    def set_skill_enabled(self, name, enabled):
        if name == "builtin-x":
            raise ValueError("内置技能不可停用")
        if name == "nope":
            raise ValueError("技能不存在")
        return {"ok": True, "name": name, "enabled": bool(enabled)}

    def discover_skills(self, goal, constraints="", max_results=5):
        return {"ok": True, "items": [{"name": "found", "goal": goal}]}

    def mcp_status(self):
        return {"enabled": True, "servers": [
            {"name": "demo", "command": "python", "args": [],
             "tools": [{"name": "demo_echo",
                        "permissions": {"read": True}}],
             "stats": {"connections": 1, "calls": 3}}]}


def _mk_server(tmp_path):
    from wuxing.shell.web.api import register_api
    from wuxing.shell.web.manager import EngineManager
    from wuxing.shell.web.server import ShellServer
    hub = EventHub()
    mgr = EngineManager(hub=hub, engine_factory=lambda w, a: _FakeEngine(w, a),
                        state_path=tmp_path / "ws.json")
    srv = ShellServer(port=0, hub=hub)
    register_api(srv, mgr)
    port = srv.start()
    return srv, port, mgr


def _request(port, method, path, body=None, headers=None):
    c = http.client.HTTPConnection("127.0.0.60", port, timeout=5)
    c.request(method, path, body=body, headers=headers or {})
    r = c.getresponse()
    data = r.read()
    status = r.status
    c.close()
    return status, data


def _mut(port, method, path, payload=None):
    return _request(port, method, path,
                    body=json.dumps(payload) if payload is not None else None,
                    headers={"X-Wuxing": "1",
                             "Content-Type": "application/json"})


def test_skills_manage_endpoints(tmp_path):
    srv, port, mgr = _mk_server(tmp_path)
    try:
        # 无工作区 → 404（管理面需引擎）
        status, _d = _request(port, "GET", "/api/v1/skills")
        assert status == 404

        wd = tmp_path / "proj"
        wd.mkdir()
        mgr.open_workspace(str(wd))

        status, data = _request(port, "GET", "/api/v1/skills")
        assert status == 200 and json.loads(data)["skills"][0]["name"] == "demo"

        status, data = _request(port, "GET", "/api/v1/skills/demo")
        assert status == 200 and "正文" in json.loads(data)["content"]
        status, _d = _request(port, "GET", "/api/v1/skills/nope")
        assert status == 404

        status, data = _mut(port, "POST", "/api/v1/skills/install",
                            {"name": "demo2", "description": "x",
                             "content": "---\nname: demo2\n---\n"})
        assert status == 200 and json.loads(data)["ok"] is True

        status, data = _mut(port, "POST", "/api/v1/skills/discover",
                            {"goal": "写周报"})
        assert status == 200 and json.loads(data)["items"][0]["name"] == "found"

        status, data = _mut(port, "DELETE", "/api/v1/skills/demo2")
        assert status == 200 and json.loads(data)["ok"] is True
        # 内置保护 → 422（ValueError → _guard 映射）
        status, _d = _mut(port, "DELETE", "/api/v1/skills/builtin-x")
        assert status == 422

        # M7 #5（A1）：启停端点
        status, data = _mut(port, "PATCH", "/api/v1/skills/demo",
                            {"enabled": False})
        assert status == 200 and json.loads(data)["enabled"] is False
        status, _d = _mut(port, "PATCH", "/api/v1/skills/demo", {})
        assert status == 422  # enabled 必填
        status, _d = _mut(port, "PATCH", "/api/v1/skills/builtin-x",
                          {"enabled": False})
        assert status == 422  # 内置不可停用
    finally:
        srv.stop()


def test_mcp_status_and_reload(tmp_path):
    srv, port, mgr = _mk_server(tmp_path)
    wd = tmp_path / "proj"
    wd.mkdir()
    mgr.open_workspace(str(wd))
    try:
        status, data = _request(port, "GET", "/api/v1/mcp")
        assert status == 200
        payload = json.loads(data)
        assert payload["servers"][0]["tools"][0]["name"] == "demo_echo"
        assert payload["servers"][0]["stats"]["calls"] == 3

        status, data = _mut(port, "POST", "/api/v1/mcp/reload")
        assert status == 200 and json.loads(data)["ok"] is True
        assert json.loads(data)["reloaded"] >= 1
    finally:
        srv.stop()


def test_maintenance_reports_skills_dir(tmp_path):
    """T5.4：数据与维护概览含技能目录（路径 + 数量）。"""
    srv, port, _mgr = _mk_server(tmp_path)
    try:
        status, data = _request(port, "GET", "/api/v1/maintenance")
        assert status == 200
        payload = json.loads(data)
        assert "path" in payload["skills"] and "count" in payload["skills"]
    finally:
        srv.stop()
