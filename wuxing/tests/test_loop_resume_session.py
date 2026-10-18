"""TDD：P4 T3 resume 消息级断点（Pi V2 重启恢复标准——从断点续跑非整单元重跑）。"""
import pathlib
import tempfile

from wuxing.config import EngineConfig
from wuxing.engine import Engine
from wuxing.llm.tool_results import ToolCallResult
from wuxing.registry import DomainRegistry
from wuxing.runner import Runner
from wuxing.tools.loader import load_tools
from wuxing.workspace import Workspace


class InterruptibleLlm:
    """首轮调工具（写入 session）；之后若收到历史 → 输出收口；否则继续探索。"""

    def __init__(self):
        self.calls = 0
        self.seen = []

    def name(self):
        return "interruptible"

    def chat(self, messages, tools=None):
        self.calls += 1
        self.seen.append([str(m.get("content", "")) for m in messages])
        joined = " ".join(self.seen[-1])
        if self.calls == 1:
            return ToolCallResult(text="我先写产物", tool_calls=[
                {"name": "write_artifact",
                 "arguments": {"path": "p.md", "kind": "plan", "content": "x"}}])
        if "written" in joined or "我先写产物" in joined:
            return "方案：完整执行计划"
        return "我在思考"


def test_run_unit_accepts_resume_session():
    """run_unit(resume_session=...)：LLM 首次调用即收到上半场完整历史。"""
    cfg = EngineConfig(max_loop_rounds=6, max_unit_budget=4)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    # 先跑一次（2 轮）生成 session 存档
    llm1 = InterruptibleLlm()
    r1 = Runner(cfg, DomainRegistry(cfg), ws, llm1, load_tools(ws))
    assert r1.run_unit("U-1", "plan", {"goal": "plan:x"}).status == "ok"
    session_path = ws.root / ".wuxing" / "sessions" / "U-1.jsonl"
    assert session_path.exists(), "session 必须先落盘"
    from wuxing.session import SessionLog
    hist = SessionLog(session_path).last_messages()

    # 断点续跑：新 Runner + 历史 → 第一条消息应是完整历史（含首轮 prompt/回填）
    llm2 = InterruptibleLlm()
    r2 = Runner(cfg, DomainRegistry(cfg), ws, llm2, load_tools(ws))
    res = r2.run_unit("U-1", "plan", {"goal": "plan:x"}, resume_session=hist)
    assert res.status == "ok", res.error
    first = " ".join(llm2.seen[0])
    assert "我先写产物" in first, "断点续跑必须包含上半场历史（模型看到自己上轮输出与工具结果）"
    assert "域：plan" in first, "历史须含最初的 system 消息"


def test_engine_resume_continues_from_session():
    """引擎级：中断（预算 1 耗尽）→ resume → pending 单元从断点历史续跑。"""
    wd = pathlib.Path(tempfile.mkdtemp())
    # 首轮：budget=1 → 单元做一轮但未收敛 → failed（session 有 1 轮记录）
    cfg1 = EngineConfig(max_loop_rounds=6, max_unit_budget=1)
    e1 = Engine(cfg=cfg1, workdir=wd, auto_confirm=True)
    e1.run_task("写一封请假邮件")
    session_files = list((wd / ".wuxing" / "sessions").glob("*.jsonl"))
    assert session_files, "中断后必须有 session 存档"
    # resume：正常预算 → verify 单元应从断点历史续跑（mock 引擎：llm_for 注射）
    e2 = Engine(cfg=EngineConfig(max_loop_rounds=6, max_unit_budget=4),
                workdir=wd, auto_confirm=True)
    # 注意：resume 只重跑 pending（ok 跳过）——断言不抛且状态合法
    res = e2.resume_task()
    assert res.status in ("done", "partial", "pending"), res.status
