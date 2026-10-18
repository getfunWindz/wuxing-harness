"""TDD：回复缓存对象序列化——ToolCallResult 必须可落盘/还原。

回归场景：P0 T3 后 mock 返回 ToolCallResult（对象）→ ReplyCache json.dumps
序列化失败（except 吞掉）→ 缓存永不落盘 → 跨引擎恢复/repeat 基准归零。
"""
import json
import pathlib
import tempfile

from wuxing.cache import ReplyCache
from wuxing.llm.tool_results import ToolCallResult


def test_reply_cache_persists_tool_call_result():
    """ToolCallResult 写入缓存后必须真正落盘，且重新加载后保持结构。"""
    path = pathlib.Path(tempfile.mkdtemp()) / "reply_cache.json"
    rc = ReplyCache(path)
    tcr = ToolCallResult(text="方案：完整", tool_calls=[
        {"name": "write_artifact",
         "arguments": {"path": "a.md", "kind": "plan", "content": "内容"}}])
    rc.put("plan|p", tcr)
    # 落盘断言：文件必须存在且可解析（旧缺陷：json.dumps 失败被吞、文件不存在）
    assert path.exists(), "缓存值必须真正写盘（旧缺陷：对象序列化失败静默吞掉）"
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert len(raw["entries"]) == 1, "序列化后的 entries 必须保留"
    # 新实例加载还原为结构化对象（跨引擎复用场景）
    rc2 = ReplyCache(path)
    out = rc2.get("plan|p")
    assert hasattr(out, "tool_calls"), "还原后必须是 ToolCallResult（含工具调用）"
    assert out.text == "方案：完整"
    assert out.tool_calls[0]["name"] == "write_artifact"
