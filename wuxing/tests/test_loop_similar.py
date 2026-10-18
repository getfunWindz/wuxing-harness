"""TDD：P1 T3 R3 语义缓存（债 4——变体微漂移可复用，真变体不误判）。

阈值依据（实测）：标点/空白微漂移 jieba Jaccard ≈ 0.80；真变体 ≤ 0.57 → 默认 0.75。
"""
import pathlib
import tempfile

from wuxing.cache import ReplyCache
from wuxing.config import EngineConfig
from wuxing.llm.tool_results import ToolCallResult
from wuxing.registry import DomainRegistry
from wuxing.runner import Runner
from wuxing.tools.loader import load_tools
from wuxing.workspace import Workspace


def test_similar_get_hits_on_punctuation_drift():
    """标点漂移（J≈0.8 ≥ 0.75）：精确 miss → 语义命中。"""
    rc = ReplyCache(pathlib.Path(tempfile.mkdtemp()) / "rc.json")
    rc.put("写一封请假邮件", "v1")
    val, sim = rc.similar_get("写一封请假邮件。")
    assert val == "v1", f"微漂移应命中：{val!r}"
    assert sim >= 0.75
    assert rc.similar_hits == 1


def test_similar_get_misses_on_real_variant():
    """真变体（J≈0.5 < 0.75）：不得命中（安全边界）。"""
    rc = ReplyCache(pathlib.Path(tempfile.mkdtemp()) / "rc.json")
    rc.put("写一封请假邮件", "v1")
    val, _ = rc.similar_get("写请假邮件给经理")
    assert val is None, f"真变体不得误命中：{val!r}"
    assert rc.similar_hits == 0


def test_similar_disabled_when_threshold_zero():
    """阈值 0 = 语义层关闭（仅精确）。"""
    rc = ReplyCache(pathlib.Path(tempfile.mkdtemp()) / "rc.json",
                    similar_threshold=0.0)
    rc.put("写一封请假邮件", "v1")
    val, sim = rc.similar_get("写一封请假邮件。")
    assert val is None and sim == 0.0 and rc.similar_hits == 0


def test_similar_get_does_not_tokenize_on_query():
    """性能防护：similar_get 不得在查询热路径分词（O(N) jieba = 321 套件级灾难）。

    put 时建索引、查询纯 set 运算——索引随 evict 同步维护。
    """
    import wuxing.cache as cache_mod
    rc = ReplyCache(pathlib.Path(tempfile.mkdtemp()) / "rc.json")
    for i in range(50):
        rc.put(f"任务{i}：写一封请假邮件", f"v{i}")
    calls = {"n": 0}
    orig = cache_mod.jieba.lcut

    def counting(text):
        calls["n"] += 1
        return orig(text)

    cache_mod.jieba.lcut = counting
    try:
        val, _ = rc.similar_get("任务25：写一封请假邮件")
        assert val is not None, "索引构建后查询应命中"
        assert calls["n"] <= 1, f"查询热路径仅允许查询键自身分词（调用 {calls['n']} 次）"
    finally:
        cache_mod.jieba.lcut = orig


def test_engine_shape_semantic_reuse_on_drift():
    """二跑（标点漂移）：形状化语义复用（真 LLM 形状化昂贵——微漂移应免调用）。

    机制测试固定 mock 形状化路径：真实形状化默认开且无凭据时降级结果不写缓存
    （配好凭据后可重跑真实形状化）——会遮蔽本测试的语义复用意图（2026-09-18）。
    """
    import pathlib
    import tempfile

    from wuxing.config import EngineConfig
    from wuxing.engine import Engine

    wd = pathlib.Path(tempfile.mkdtemp())
    e1 = Engine(cfg=EngineConfig(use_real_shape=False), workdir=wd,
                auto_confirm=True)
    e1.run_task("写一封请假邮件")
    e2 = Engine(cfg=EngineConfig(use_real_shape=False), workdir=wd,
                auto_confirm=True)
    r2 = e2.run_task("写一封请假邮件。")
    m = r2.metrics["cache"]
    assert m["shape"]["similar_hits"] >= 1, f"形状化语义复用应命中：{m}"
    assert r2.metrics["llm_calls"] == 0, "全链复用：LLM 一次都不调用"


def test_runner_similar_cache_skips_llm_call():
    """Runner 集成：精确 miss + 语义命中 → 复用输出（LLM 不被调用）+ 日志标注。"""
    rc = ReplyCache(pathlib.Path(tempfile.mkdtemp()) / "rc.json",
                    similar_threshold=0.75)
    # 预置近似任务的首轮回复（与 runner 实际 prompt 同构；仅标点漂移——新契约）
    # 双模式批 1（2026-09-23）：默认极简模式心跳让位（设计 §4.1）——预置键同步
    # 为极简装配（无心跳行）；非极简模式仍带 PROGRESS_HEARTBEAT_CONTRACT
    rc.put("plan|任务背景：写一封请假邮件\n请为任务制定方案：写一封请假邮件",
           ToolCallResult(text="方案：完整执行计划", tool_calls=[
               {"name": "write_artifact",
                "arguments": {"path": "p.md", "kind": "plan", "content": "x"}}]))

    class NeverCalled:
        def __init__(self):
            self.calls = 0

        def name(self):
            return "never"

        def chat(self, messages, tools=None):
            self.calls += 1
            raise AssertionError("语义命中时 LLM 不得被调用")

    cfg = EngineConfig(max_loop_rounds=6, max_unit_budget=3)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    llm = NeverCalled()
    r = Runner(cfg, DomainRegistry(cfg), ws, llm, load_tools(ws), reply_cache=rc)
    res = r.run_unit("U-1", "plan", {"goal": "写一封请假邮件。",
                                     "task": "写一封请假邮件。"})
    assert res.status == "ok"
    assert llm.calls == 0, "高相似复用不得调用 LLM"
    assert any("similar" in log for log in res.logs), "语义命中必须留痕（审计）"
