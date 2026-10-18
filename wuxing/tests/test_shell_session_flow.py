"""TDD：Web 提交 → 会话自动新建/延续（验收修复①，2026-09-20）。

用户验收：初始页面说第一句对话后未自动新建会话。
修复：manager.submit 支持 session 参数——未指定则自动新建
`conversation-<ts>.jsonl` 并把该轮（user_text/arts/summary）追加至会话文件；
指定则续写（多轮累积）。
"""
import json
import pathlib

from wuxing.shell.web.hub import EventHub


class _Result:
    def __init__(self, status="done"):
        self.status = status
        self.report = "报告"
        self.artifacts = []
        self.metrics = {}


class FakeEngine:
    def __init__(self, workdir, auto_confirm=False):
        self.workdir = workdir
        self.seen = []

    def start_session(self, conversation_path=None):
        """修复①（2026-09-20）：manager 经引擎公开 API 建会话——测试桩用真实实现。"""
        from wuxing.conversation import ConversationState
        from wuxing.session_api import ConversationSession
        return ConversationSession(self, ConversationState(conversation_path))

    def run_task(self, text, on_event=None, conversation=None,
                 references=None, overrides=None):
        self.seen.append({"text": text, "conversation": conversation})
        return _Result()


def _mk(tmp_path):
    from wuxing.shell.web.manager import EngineManager
    mgr = EngineManager(hub=EventHub(),
                        engine_factory=lambda wd, ac: FakeEngine(wd, ac),
                        state_path=tmp_path / "ws.json")
    wd = tmp_path / "proj"
    wd.mkdir()
    ws = mgr.open_workspace(str(wd))
    return mgr, ws, wd


def _session_files(wd: pathlib.Path) -> list:
    base = wd / ".wuxing"
    if not base.is_dir():
        return []
    return sorted(p.name for p in base.glob("conversation-*.jsonl"))


def _rows(wd: pathlib.Path, name: str) -> list:
    text = (wd / ".wuxing" / name).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def test_submit_auto_creates_session_with_turn(tmp_path):
    mgr, ws, wd = _mk(tmp_path)
    assert _session_files(wd) == []
    run_id = mgr.submit(ws["id"], "你好，第一句对话")
    mgr.wait(run_id, timeout=5)
    files = _session_files(wd)
    assert len(files) == 1, files
    rows = _rows(wd, files[0])
    assert len(rows) == 1 and rows[0]["user_text"] == "你好，第一句对话", rows
    assert mgr.get_run(run_id)["session"] == files[0]


def test_submit_continues_named_session(tmp_path):
    mgr, ws, wd = _mk(tmp_path)
    run1 = mgr.submit(ws["id"], "第一句", session="my-chat")
    mgr.wait(run1, timeout=5)
    run2 = mgr.submit(ws["id"], "第二句", session="my-chat.jsonl")
    mgr.wait(run2, timeout=5)
    assert _session_files(wd) == [], "命名会话不落入默认前缀扫描（按指定名存取）"
    rows = _rows(wd, "my-chat.jsonl")
    assert [r["user_text"] for r in rows] == ["第一句", "第二句"], rows
    assert mgr.get_run(run2)["session"] == "my-chat.jsonl"


def test_submit_rejects_traversal_session(tmp_path):
    import pytest
    mgr, ws, _wd = _mk(tmp_path)
    with pytest.raises(ValueError):
        mgr.submit(ws["id"], "x", session="../escape")
