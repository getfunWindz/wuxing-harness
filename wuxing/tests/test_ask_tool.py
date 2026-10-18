"""E2-5（A10）：ask_user 工具（校验矩阵/挂起标记/白名单/串行/装载）。"""
import pathlib
import tempfile

from wuxing.domains.defaults import DEFAULT_DOMAINS
from wuxing.runner_support import _is_side_effect_free
from wuxing.tools.ask_tool import AskUserTool
from wuxing.tools.loader import ToolLoaderConfig, load_tools
from wuxing.workspace import Workspace


def _q(title="范围？", options=("A", "B"), multi=False):
    return {"title": title, "options": list(options), "multi": multi}


def test_ask_tool_validates_question_count():
    t = AskUserTool()
    for bad in ([], [_q()] * 4):
        res = t.execute(questions=bad)
        assert res.status == "error" and "1-3" in res.error


def test_ask_tool_validates_fields():
    t = AskUserTool()
    cases = [
        "x",
        [{"title": "", "options": ["A", "B"]}],
        [_q(options=("A",))],
        [_q(options=("A", "B", "C", "D", "E"))],
        [_q(title="x" * 201)],
        [_q(title="  ")],
        [{"title": "T", "options": ["A", "B"], "multi": "yes"}],
        [{"title": "T", "options": ["A", ""]}],
    ]
    for bad in cases:
        res = t.execute(questions=bad)
        assert res.status == "error", bad


def test_ask_tool_returns_pending_marker():
    t = AskUserTool()
    res = t.execute(questions=[_q(), _q(title="第二题", options=("X", "Y"))])
    assert res.status == "needs_answer"
    assert "范围" in res.content and "第二题" in res.content
    assert t.last_questions == [
        {"title": "范围？", "options": ["A", "B"], "multi": False},
        {"title": "第二题", "options": ["X", "Y"], "multi": False}]
    assert t.permission()["read"] is True
    assert t.permission()["write"] is False


def test_ask_tool_whitelist_plan_execute_only():
    for d in ("plan", "execute"):
        assert "ask_user" in DEFAULT_DOMAINS[d].tool_whitelist
    for d in ("verify", "user"):
        assert "ask_user" not in DEFAULT_DOMAINS[d].tool_whitelist


def test_ask_tool_registered_and_serial():
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    reg = load_tools(ws, ToolLoaderConfig(mcp_servers=[]))
    assert "ask_user" in {t.name() for t in reg.list()}
    # 挂起语义：不参与并行只读批（保序串行——Q7 同批独占）
    assert _is_side_effect_free("ask_user", reg) is False
