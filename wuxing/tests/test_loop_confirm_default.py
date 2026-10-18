"""TDD：P3 T1 人工介入默认化（知识库企业级「interrupt on——该问人就问人」）。"""
import pathlib
import tempfile

from wuxing.config import EngineConfig
from wuxing.engine import Engine
from wuxing.llm.mock import MockLlmProvider
from wuxing.registry import DomainRegistry
from wuxing.runner import Runner
from wuxing.tools.loader import load_tools
from wuxing.workspace import Workspace


def test_engine_default_hangs_verify():
    """默认构造 → verify 单元 needs_confirm（人工介入开启——不再全自动）。"""
    eng = Engine(workdir=pathlib.Path(tempfile.mkdtemp()))
    assert eng.auto_confirm is False, "默认必须人工介入（auto_confirm=False）"
    res = eng._build_fragments("写一封请假邮件")  # 直接构造碎片路径
    assert res
    # 用 runner 单测 verify 域挂起（快路径——模拟引擎装配：ConfirmGate 注入）
    cfg = EngineConfig()
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    from wuxing.confirm_gate import ConfirmGate
    reg = DomainRegistry(cfg)
    r = Runner(cfg, reg, ws, MockLlmProvider(), load_tools(ws),
               confirm_gate=ConfirmGate(cfg, registry=reg),
               auto_confirm=False)
    unit = r.run_unit("U-1", "verify", {"result": "r"})
    assert unit.status == "needs_confirm", \
        f"verify 域默认必须挂起等待人工（status={unit.status}）"


def test_auto_confirm_explicit_resumes():
    """显式 auto_confirm=True → 不挂起（CI/headless 路径）。"""
    cfg = EngineConfig()
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    r = Runner(cfg, DomainRegistry(cfg), ws, MockLlmProvider(), load_tools(ws),
               auto_confirm=True)
    unit = r.run_unit("U-1", "verify", {"result": "r"})
    assert unit.status != "needs_confirm"


def test_plan_user_domains_not_blocked_by_default():
    """非 always_confirm 域（plan/execute）默认不挂起（只关键碎片才问人）。"""
    cfg = EngineConfig()
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    r = Runner(cfg, DomainRegistry(cfg), ws, MockLlmProvider(), load_tools(ws),
               auto_confirm=False)
    unit = r.run_unit("U-1", "plan", {"goal": "plan:x"})
    assert unit.status == "ok", f"plan 域不受确认关口影响：{unit.status}"
