"""模式化假引擎服务（A 测试：功能连接 + 健壮性）——本地资产，不入库。

用法：python e2e/shell/serve_fake_modes.py <port> [mode] [base_dir]
  mode: done（默认）/ confirm / slow / error
事实端点：GET /fake/meta → {mode, runs, confirms}（供 E2E 做服务器事实断言）
"""
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from wuxing.shell.web.api import register_api
from wuxing.shell.web.hub import EventHub
from wuxing.shell.web.manager import EngineManager
from wuxing.shell.web.server import ShellServer, json_response

MODE = "done"
RUNS = {"count": 0}
CONFIRMS = {"count": 0}


class UnitStarted:
    def __init__(self, unit_id, domain_id):
        self.unit_id, self.domain_id = unit_id, domain_id


class UnitDone:
    def __init__(self, unit_id, domain_id, status):
        self.unit_id, self.domain_id, self.status = unit_id, domain_id, status


class UnitNeedsConfirm:
    def __init__(self, unit_id, domain_id, reason=""):
        self.unit_id, self.domain_id, self.reason = unit_id, domain_id, reason


class TaskDone:
    def __init__(self, status):
        self.status = status


class _Result:
    def __init__(self, status="done", report="mock 报告", artifacts=None,
                 metrics=None):
        self.status = status
        self.report = report
        self.artifacts = artifacts or []
        self.metrics = metrics or {}


class FakeEngine:
    def __init__(self, workdir, auto_confirm=False):
        self.workdir, self.auto_confirm = workdir, auto_confirm

    def start_session(self, conversation_path=None):
        """修复①（2026-09-20）：manager 经引擎公开 API 建会话——A 套件夹具同口径。"""
        from wuxing.conversation import ConversationState
        from wuxing.session_api import ConversationSession
        return ConversationSession(self, ConversationState(conversation_path))

    def run_task(self, text, on_event=None, references=None, conversation=None,
                 overrides=None):
        RUNS["count"] += 1
        mode = MODE
        if mode == "error":
            raise RuntimeError("模拟引擎失败")
        if mode == "slow":
            time.sleep(1.5)
        if on_event:
            on_event(UnitStarted("F-1", "execute"))
        if mode == "confirm":
            if on_event:
                on_event(UnitNeedsConfirm("F-1", "execute", "需要人工批准"))
                on_event(TaskDone("pending"))
            return _Result(status="pending", report="等待确认")
        time.sleep(0.2)
        if on_event:
            on_event(UnitDone("F-1", "execute", "ok"))
            on_event(TaskDone("done"))
        return _Result()

    def confirm_units(self, items, reason="", on_event=None):
        CONFIRMS["count"] += 1
        if on_event:
            on_event(UnitDone("F-1", "execute", "ok"))
            on_event(TaskDone("done"))
        return _Result(report="确认后完成")

    def resume_task(self, on_event=None):
        return _Result()

    def cancel_task(self):
        return True

    def list_skills(self):
        return []


def main():
    global MODE
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    MODE = sys.argv[2] if len(sys.argv) > 2 else "done"
    base = (pathlib.Path(sys.argv[3]) if len(sys.argv) > 3
            else pathlib.Path(__file__).resolve().parent / "fake-modes")
    base.mkdir(parents=True, exist_ok=True)
    static = (pathlib.Path(__file__).resolve().parents[2]
              / "wuxing" / "shell" / "web" / "static")
    hub = EventHub(journal_path=base / "events.jsonl")
    mgr = EngineManager(hub=hub,
                        engine_factory=lambda wd, ac: FakeEngine(wd, ac),
                        state_path=base / "ws.json")

    def fake_meta(_req):
        return json_response({"mode": MODE, "runs": RUNS["count"],
                              "confirms": CONFIRMS["count"]})

    srv = ShellServer(port=port, hub=hub, static_dir=static)
    register_api(srv, mgr)
    srv.add_route("GET", r"^/fake/meta$", fake_meta)
    port = srv.start()
    for name in ("fake-ws", "fake-ws2"):
        d = base / name
        d.mkdir(exist_ok=True)
        mgr.open_workspace(str(d))
    print(f"URL http://127.0.0.60:{port}/ mode={MODE}", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        srv.stop()


if __name__ == "__main__":
    main()
