"""TDD · Task A1：pi 式总体回复生成（Engine.generate_task_reply）。

用户裁决 2026-10-01：回合收口以「模型生成的总体回复消息」直接呈现——
终端状态（done/partial/failed）后一次轻量 LLM 调用生成，失败/关闭/非终态
静默回退（调用方用机械摘要兜底）；不得阻断主流程。
"""
import pathlib
import tempfile
import types

from wuxing.config import EngineConfig
from wuxing.engine import Engine
from wuxing.protocols import UnitResult


class _ReplyLlm:
    """总体回复用假 LLM：记录 prompt，返回固定文本。"""

    def __init__(self, reply="总结回复：已创建 greeting.txt 两行，验收通过。"):
        self.prompts = []
        self._reply = reply

    def name(self):
        return "reply-llm"

    def chat(self, messages, tools=None):
        self.prompts.append(messages[-1]["content"])
        return self._reply


def test_generate_task_reply_uses_llm_and_caps():
    llm = _ReplyLlm()
    eng = Engine(workdir=pathlib.Path(tempfile.mkdtemp()), llm=llm,
                 auto_confirm=True,
                 cfg=EngineConfig(max_loop_rounds=2, max_unit_budget=2))
    res = types.SimpleNamespace(
        status="done", task_text="写 greeting.txt",
        units=[UnitResult(unit_id="F-1", domain_id="execute", status="ok",
                          deliverables=["greeting.txt"], reply="执行完成")])
    out = eng.generate_task_reply(res)
    assert out.startswith("总结回复")
    assert "总体回复" in llm.prompts[0] and "greeting.txt" in llm.prompts[0]
    # 关闭 / 非终态 → 空（调用方回退）
    eng.cfg.task_reply_enabled = False
    assert eng.generate_task_reply(res) == ""
    eng.cfg.task_reply_enabled = True
    res.status = "pending"
    assert eng.generate_task_reply(res) == ""


def test_generate_task_reply_caps_length():
    """超长生成截断到 task_reply_max_chars（默认 800）。"""
    llm = _ReplyLlm(reply="长" * 2000)
    eng = Engine(workdir=pathlib.Path(tempfile.mkdtemp()), llm=llm,
                 auto_confirm=True,
                 cfg=EngineConfig(max_loop_rounds=2, max_unit_budget=2,
                                  task_reply_max_chars=100))
    res = types.SimpleNamespace(status="done", task_text="t", units=[])
    out = eng.generate_task_reply(res)
    assert out and len(out) <= 100


def test_generate_task_reply_failure_returns_empty():
    class _BoomLlm:
        def name(self):
            return "boom"

        def chat(self, messages, tools=None):
            raise RuntimeError("provider down")

    eng = Engine(workdir=pathlib.Path(tempfile.mkdtemp()), llm=_BoomLlm(),
                 auto_confirm=True,
                 cfg=EngineConfig(max_loop_rounds=2, max_unit_budget=2))
    res = types.SimpleNamespace(status="done", task_text="t", units=[])
    assert eng.generate_task_reply(res) == ""   # 静默回退，不阻断


def test_generate_task_reply_failure_traced():
    """真机发现（2026-10-03）：生成失败静默回退——必须落 trace（可归因）。

    背景：壳端真机两次任务，一次生成成功、一次回退为单元原始文本（DSML 块）；
    回退只有 logger.debug（默认不显），无法归因。
    """
    class _BoomLlm:
        def name(self):
            return "boom"

        def chat(self, messages, tools=None):
            raise RuntimeError("provider down")

    eng = Engine(workdir=pathlib.Path(tempfile.mkdtemp()), llm=_BoomLlm(),
                 auto_confirm=True,
                 cfg=EngineConfig(max_loop_rounds=2, max_unit_budget=2))
    res = types.SimpleNamespace(status="done", task_text="t", units=[])
    assert eng.generate_task_reply(res) == ""
    rows = eng.trace.load()
    fb = [r for r in rows if r["event"] == "task_reply_fallback"]
    assert fb, "回退必须落 trace（task_reply_fallback）"
    assert "provider down" in str(fb[0].get("error", "")), fb[0]


def test_generate_task_reply_success_traced():
    """生成成功也落 trace（chars——账实可见）；与回退同为可观测面。"""
    llm = _ReplyLlm()
    eng = Engine(workdir=pathlib.Path(tempfile.mkdtemp()), llm=llm,
                 auto_confirm=True,
                 cfg=EngineConfig(max_loop_rounds=2, max_unit_budget=2))
    res = types.SimpleNamespace(status="done", task_text="t", units=[])
    out = eng.generate_task_reply(res)
    assert out
    rows = eng.trace.load()
    ok = [r for r in rows if r["event"] == "task_reply_generated"]
    assert ok and int(ok[0].get("chars", 0)) == len(out), ok
