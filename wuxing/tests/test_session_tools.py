"""TDD · Wave-1 Task C1：会话检索工具（session_search——模型可用的历史回看）。

范围=当前工作区 `.wuxing/*.jsonl`（排除内部 jsonl）；首期子串匹配
（大小写不敏感）；结构化返回 会话文件 · 第N轮 · 角色/字段 · 片段；只读。
"""
import json


def test_session_search_finds_history(tmp_path):
    wd = tmp_path / ".wuxing"
    wd.mkdir()
    (wd / "conversation-1.jsonl").write_text(
        json.dumps({"round": 1, "user_text": "做站点",
                    "summary": "done", "reply": "站点已完成，缓存 75%"},
                   ensure_ascii=False) + "\n"
        + json.dumps({"round": 2, "user_text": "改颜色",
                      "reply": "已改为主色青碧"}, ensure_ascii=False) + "\n",
        encoding="utf-8")
    (wd / "trace.jsonl").write_text('{"event":"secret"}\n', encoding="utf-8")
    from wuxing.tools.session_tools import SessionSearchTool
    from wuxing.workspace import Workspace
    r = SessionSearchTool(Workspace(tmp_path)).execute(query="缓存")
    assert r.status == "ok" and "conversation-1" in r.content and "75%" in r.content
    assert "trace" not in r.content                    # 内部 jsonl 排除
    assert "No matching" in SessionSearchTool(
        Workspace(tmp_path)).execute(query="不存在词").content


def test_session_search_empty_query_rejected(tmp_path):
    from wuxing.tools.session_tools import SessionSearchTool
    from wuxing.workspace import Workspace
    r = SessionSearchTool(Workspace(tmp_path)).execute(query="  ")
    assert r.status == "error" and "empty query" in (r.error or "")


def test_internal_jsonl_sets_in_sync():
    """引擎副本与壳副本不得漂移（幽灵会话/内部文件语义单一来源）。"""
    from wuxing.shell.web.api_routes.base import _INTERNAL_JSONL as shell_set
    from wuxing.tools.session_tools import _INTERNAL_JSONL as engine_set
    assert engine_set == shell_set
