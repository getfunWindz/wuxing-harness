"""E3-5/H6：召回注入 call-time 隔离（不写 transcript/session）。

计划：docs/plans/2026-10-04-wuxing-recall-calltime.md。
语义：共享经验段仍在调用载荷原位（缓存前缀不变），但：
- 会话档案（SessionLog）不写入注入帧；
- provider 入参不含内部键（`_call_time`）；
- resume/continue 从干净历史重建后重注入一次。
"""
import pathlib

from wuxing.config import EngineConfig
from wuxing.registry import DomainRegistry
from wuxing.runner import Runner
from wuxing.session import SessionLog
from wuxing.tools.loader import load_tools
from wuxing.workspace import Workspace


class _CaptureLlm:
    """假 LLM：记录每次 chat 入参 + 返回收敛文本。"""

    def __init__(self):
        self.seen = []

    def name(self):
        return "capture"

    def spec(self):
        return "capture"

    def chat(self, messages, tools=None):
        self.seen.append([dict(m) for m in messages])
        return "方案：完成"


class _Shared:
    """共享经验段 stub（有向增量注入面）。"""

    def __init__(self):
        self.calls = []

    def for_next(self, unit_id):
        self.calls.append(unit_id)
        return "[碎片 F-0000 plan/ok 经验]\n旧经验正文"


def _mk(tmp_path):
    cfg = EngineConfig()
    ws = Workspace(pathlib.Path(tmp_path))
    llm = _CaptureLlm()
    r = Runner(cfg, DomainRegistry(cfg), ws, llm, load_tools(ws))
    r.shared = _Shared()
    return r, ws, llm


def test_recall_frame_not_persisted(tmp_path):
    """注入段进调用载荷、不进会话档案；内部键不外发给 provider。"""
    r, _ws, llm = _mk(tmp_path)
    res = r.run_unit("U-1", "plan", {"goal": "plan:x"})
    assert res.status == "ok"
    # 1) 调用载荷含经验段（功能不变——尾部位置）
    assert llm.seen, "应有 LLM 调用"
    assert "旧经验正文" in str(llm.seen[0][-1].get("content", "")), \
        "注入帧应保持消息尾部位置"
    # 2) 会话档案不含注入帧
    sessions = list(
        (pathlib.Path(tmp_path) / ".wuxing" / "sessions").glob("*.jsonl"))
    assert sessions, "会话档案应存在"
    for p in sessions:
        assert "旧经验正文" not in p.read_text(encoding="utf-8"), \
            "注入帧不得写会话档案（防自污染）"
    # 3) provider 入参无内部键（`_call_time` 不外发）
    for payload in llm.seen:
        for m in payload:
            assert not any(str(k).startswith("_") for k in m), \
                f"内部键外发给 provider：{m}"
    # 4) 实时历史中注入帧带标注（call-time 可识别——不计入历史口径）
    frames = [m for m in r._messages
              if isinstance(m, dict) and m.get("_call_time")]
    assert frames and "旧经验正文" in str(frames[0].get("content", ""))


def test_resume_reinjects_from_clean_history(tmp_path):
    """档案（无注入帧）重建历史 → 新单元调用时重注入一次。"""
    r, _ws, _llm = _mk(tmp_path)
    r.run_unit("U-1", "plan", {"goal": "plan:x"})
    session_file = next(
        (pathlib.Path(tmp_path) / ".wuxing" / "sessions").glob("*.jsonl"))
    hist = SessionLog(session_file).last_messages()
    assert hist, "档案应可回放"
    assert not any("旧经验正文" in str(m.get("content", "")) for m in hist), \
        "重建历史必须干净（无注入帧）"
    r2, _ws2, llm2 = _mk(tmp_path)
    res = r2.run_unit("U-2", "plan", {"goal": "plan:x"}, resume_session=hist)
    assert res.status == "ok"
    assert any("旧经验正文" in str(m.get("content", ""))
               for p in llm2.seen for m in p), "重建后必须重注入一次"
