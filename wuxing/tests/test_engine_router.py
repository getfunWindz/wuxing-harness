import pathlib
import tempfile

from wuxing.config import EngineConfig
from wuxing.engine import Engine
from wuxing.llm.router import ModelRouter


def test_engine_domain_routing_uses_different_models():
    cfg = EngineConfig()
    router = ModelRouter({"plan": "mock", "execute": "mock", "_default": "mock"})
    eng = Engine(cfg=cfg, workdir=pathlib.Path(tempfile.mkdtemp()), router=router)
    result = eng.run_task("写一篇请假邮件")
    assert result.status in ("done", "partial")

def test_engine_router_provides_per_domain_llm():
    cfg = EngineConfig()
    router = ModelRouter({"plan": "mock", "_default": "mock"})
    eng = Engine(cfg=cfg, workdir=pathlib.Path(tempfile.mkdtemp()), router=router)
    assert eng.llm_for("plan").name() == "MockLlmProvider"
    assert eng.llm_for("execute").name() == "MockLlmProvider"

def test_engine_no_router_still_single_llm():
    eng = Engine(workdir=pathlib.Path(tempfile.mkdtemp()), auto_confirm=True)
    assert eng.llm_for("plan") is eng.llm  # 无 router → 单一 LLM
