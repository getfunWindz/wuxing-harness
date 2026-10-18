"""TDD：P4 T2 修正——会话记录【增量】语义（回放无重复）。

审计发现：旧实现每轮 append 全量 messages → last_messages 拼接 O(n²) 重复
（2 轮单元回放 11 条实际 5 条）——断点恢复把重复历史喂给模型。
"""
import pathlib
import tempfile

from wuxing.session import SessionLog


def test_seed_then_incremental_rounds_no_duplicate():
    """seed（初始消息）+ 每轮增量 + 终结标记 → 回放完整且无重复。"""
    ws = pathlib.Path(tempfile.mkdtemp())
    log = SessionLog(ws / "s.jsonl")
    log.seed([{"role": "system", "content": "sys"},
              {"role": "user", "content": "prompt"}])
    log.append(round_no=1, state="thinking",
               messages=[{"role": "user", "content": "第一轮文本"},
                         {"role": "user", "content": "[tool] written p.md"}])
    log.append(round_no=2, state="done", messages=[], status="ok")
    hist = log.last_messages()
    contents = [m["content"] for m in hist]
    assert len(contents) == len(set(contents)), f"回放不得重复：{contents}"
    assert [m["content"] for m in hist] == ["sys", "prompt", "第一轮文本",
                                            "[tool] written p.md"], hist


def test_last_messages_starts_with_seed():
    """回放必须从 seed（system/prompt）开始——断点续答需要完整上下文头。"""
    log = SessionLog(pathlib.Path(tempfile.mkdtemp()) / "s.jsonl")
    log.seed([{"role": "system", "content": "你是助手"}])
    log.append(round_no=1, state="thinking",
               messages=[{"role": "user", "content": "m1"}])
    hist = log.last_messages()
    assert hist[0]["content"] == "你是助手"
