import pathlib
import tempfile

from wuxing.config import EngineConfig
from wuxing.llm.mock import MockLlmProvider
from wuxing.registry import DomainRegistry
from wuxing.runner import Runner
from wuxing.tools.builtin import BUILTIN_TOOLS
from wuxing.workspace import Workspace


def test_runner_emits_needs_confirm_and_auto_confirm():
    cfg = EngineConfig(confirm_threshold=1.0)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    r = Runner(cfg, DomainRegistry(cfg), ws, MockLlmProvider(), BUILTIN_TOOLS(ws),
               confirm_gate=None, auto_confirm=True)  # auto：挂起即通过，不阻塞
    res = r.run_unit("U-1", "plan", {"goal": "plan:x"})
    assert res.status == "ok"  # 自动通过后正常跑

def test_runner_manual_confirm_returns_needs_confirm():
    cfg = EngineConfig(confirm_threshold=1.0)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    r = Runner(cfg, DomainRegistry(cfg), ws, MockLlmProvider(), BUILTIN_TOOLS(ws),
               confirm_gate=None, auto_confirm=False)
    res = r.run_unit("U-1", "plan", {"goal": "plan:x"})
    assert res.status == "needs_confirm"


def test_runner_confirm_trigger_threshold_without_gate():
    cfg = EngineConfig(confirm_threshold=1.0)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    r = Runner(cfg, DomainRegistry(cfg), ws, MockLlmProvider(), BUILTIN_TOOLS(ws),
               confirm_gate=None, auto_confirm=False)
    assert r.confirm_trigger("plan") == "threshold"


def test_runner_confirm_trigger_domain_policy():
    from wuxing.confirm_gate import ConfirmGate
    cfg = EngineConfig(confirm_threshold=0.0)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    r = Runner(cfg, DomainRegistry(cfg), ws, MockLlmProvider(), BUILTIN_TOOLS(ws),
               confirm_gate=ConfirmGate(cfg), auto_confirm=False)
    assert r.confirm_trigger("verify") == "domain_policy"
    assert r.confirm_trigger("plan") == "threshold"
