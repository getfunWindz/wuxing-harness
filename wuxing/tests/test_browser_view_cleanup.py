"""TDD · O2-2 §11.5-②：run 终态浏览器视图清理（Q4=A）+ 观测 trace。"""
from wuxing import browser_channel
from wuxing.config import EngineConfig
from wuxing.engine import Engine


class _Trace:
    def __init__(self):
        self.events = []

    def log(self, event, unit_id, domain, **fields):
        self.events.append((event, dict(fields)))


class _Client:
    def __init__(self, result=None, exc=None):
        self.calls = []
        self.result = result or {"closed": True, "active": None}
        self.exc = exc

    def call(self, cmd, timeout=None, **args):
        self.calls.append((cmd, dict(args)))
        if self.exc is not None:
            raise self.exc
        return self.result


def _engine(tmp_path, **cfg_kw):
    return Engine(cfg=EngineConfig(llm="mock", browser_enabled=True, **cfg_kw),
                  workdir=tmp_path / "eng", preset_session="sess-a")


def _patch_client(monkeypatch, client):
    monkeypatch.setattr(browser_channel.ChannelClient, "from_env",
                        classmethod(lambda cls, timeout=30.0: client))


def test_terminal_close_browser_view(monkeypatch, tmp_path):
    client = _Client()
    _patch_client(monkeypatch, client)
    eng = _engine(tmp_path)
    trace = _Trace()
    eng.trace = trace
    eng._maybe_close_browser_views("done")
    assert client.calls and client.calls[0][0] == "close"
    ident = client.calls[0][1]["identity"]
    assert ident["mode"] == "memory"
    assert len(ident["key"]) == len("wuxing-browser-") + 16 + 1 + 8
    assert any(e[0] == "browser_view_closed" and e[1].get("closed") is True
               for e in trace.events)


def test_pending_and_running_keep_view(monkeypatch, tmp_path):
    client = _Client()
    _patch_client(monkeypatch, client)
    eng = _engine(tmp_path)
    eng._maybe_close_browser_views("pending")
    eng._maybe_close_browser_views("running")
    assert client.calls == []


def test_close_failure_not_blocking(monkeypatch, tmp_path):
    client = _Client(exc=RuntimeError("boom"))
    _patch_client(monkeypatch, client)
    eng = _engine(tmp_path)
    eng._maybe_close_browser_views("done")   # 不抛（best-effort）
    assert client.calls   # 被尝试过


def test_browser_disabled_no_close(monkeypatch, tmp_path):
    client = _Client()
    _patch_client(monkeypatch, client)
    eng = Engine(cfg=EngineConfig(llm="mock"), workdir=tmp_path / "off")
    eng._maybe_close_browser_views("done")
    assert client.calls == []


def test_run_task_terminal_wires_close(monkeypatch, tmp_path):
    client = _Client()
    _patch_client(monkeypatch, client)
    eng = _engine(tmp_path)

    class _Res:
        def __init__(self):
            self.status = "done"
            self.units = []
            self.artifacts = []

    monkeypatch.setattr(eng, "_run_task_impl", lambda *a, **k: _Res())
    eng.run_task("任务")
    assert client.calls and client.calls[0][0] == "close"


def test_recovery_engine_passes_history_session(tmp_path):
    """§11.5-②：恢复引擎从历史补原 run 会话（浏览器身份 overlay 不丢）。"""
    from wuxing.shell.web.manager import EngineManager
    ws_dir = tmp_path / "ws"
    ws_dir.mkdir()
    rid = "abc123abc123"
    run_dir = ws_dir / ".wuxing" / "runs" / rid
    run_dir.mkdir(parents=True)
    (run_dir / "task_state.json").write_text("{}", encoding="utf-8")
    hist = tmp_path / "tasks.jsonl"
    hist.write_text(
        '{"ws_id": "w1", "run_id": "old", "session": "sess-old"}\n'
        f'{{"ws_id": "w1", "run_id": "{rid}", "session": "sess-a"}}\n',
        encoding="utf-8")
    captured = {}

    def factory(workdir, auto_confirm, run_id=None, preset_session=None,
                state_root=None):
        captured.update({"run_id": run_id,
                         "preset_session": preset_session})
        return object()

    mgr = EngineManager(engine_factory=factory, history_path=hist,
                        max_concurrent=4, max_parallel_runs_per_ws=3)
    mgr._ws["w1"] = {"id": "w1", "path": str(ws_dir), "name": "ws",
                     "status": "idle", "auto_confirm": True}
    mgr._recovery_engine("w1")
    assert captured["run_id"] == rid
    assert captured["preset_session"] == "sess-a"
