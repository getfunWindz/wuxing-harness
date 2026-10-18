import pathlib
import tempfile

from wuxing.config import EngineConfig
from wuxing.engine import Engine


def test_engine_brain_disabled_by_default():
    eng = Engine(workdir=pathlib.Path(tempfile.mkdtemp()), auto_confirm=True)
    assert eng.brain_enabled is False
    assert eng.brain_memory is not None  # 收集常开（2026-09-06 用户裁决）——决策注入默认关

def test_engine_brain_enabled_creates_memory():
    cfg = EngineConfig(brain_enabled=True)
    eng = Engine(cfg=cfg, workdir=pathlib.Path(tempfile.mkdtemp()))
    assert eng.brain_memory is not None
    # Router 装配了 brain
    assert eng.orchestrator.runner.brain_memory is not None

def test_engine_brain_full_flow():
    # 智脑开启 + 真执行（mock LLM 路径——成功案例写入）
    cfg = EngineConfig(brain_enabled=True)
    eng = Engine(cfg=cfg, workdir=pathlib.Path(tempfile.mkdtemp()))
    r = eng.run_task("写一篇请假邮件")
    assert r.status == "done"  # mock 路径成功
    assert len(eng.brain_memory.cases) >= 1  # 案例被写入

def test_engine_cfg_router_brain_wired():
    """P15 检查发现：cfg.router + brain_enabled 时——Router 装配必须带 brain
    （否则配置驱动模式下智脑读路径仍然断头——只有显式 router 兜底分支被修复）。"""
    cfg = EngineConfig(brain_enabled=True, router={"verify": "deepseek:deepseek-chat"})
    eng = Engine(cfg=cfg, workdir=pathlib.Path(tempfile.mkdtemp()))
    assert eng.router is not None
    assert eng.router._brain is eng.brain_memory  # 读路径已接上（此前为 None）


def test_engine_brain_auto_router_falls_back_to_default_model():
    """真测修复（REAL-2）：brain 开启 + 未配 router → 未列出域回退 cfg.llm。

    此前 `ModelRouter({})` 的 `_default` 钉死 "mock" → 四域全部静默 mock
    （真实任务却报 done——真机配置 brain_enabled=true 时全部是 mock 产出）。
    """
    from wuxing.llm.mock import MockLlmProvider
    cfg = EngineConfig(brain_enabled=True, llm="deepseek:deepseek-flash")
    eng = Engine(cfg=cfg, workdir=pathlib.Path(tempfile.mkdtemp()))
    assert eng.router is not None
    provider = eng.llm_for("execute", "一个片段")
    assert not isinstance(provider, MockLlmProvider)
    assert type(provider).__name__ == "DeepSeekLlmProvider"


def test_engine_brain_auto_router_mock_default_unchanged():
    """无真实模型（llm=mock 默认）时保持既有语义：域路由仍为 mock。"""
    from wuxing.llm.mock import MockLlmProvider
    cfg = EngineConfig(brain_enabled=True)
    eng = Engine(cfg=cfg, workdir=pathlib.Path(tempfile.mkdtemp()))
    assert isinstance(eng.llm_for("execute", "一个片段"), MockLlmProvider)
