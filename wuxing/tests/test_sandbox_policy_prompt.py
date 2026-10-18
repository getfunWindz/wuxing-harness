"""R3-2/T4：模型可见沙箱策略行（系统提示注入，字节稳定）。"""
import pathlib
import tempfile

from wuxing.config import EngineConfig
from wuxing.registry import DomainRegistry
from wuxing.runner import Runner
from wuxing.tools.loader import load_tools
from wuxing.workspace import Workspace


class ProbeLlm:
    def __init__(self):
        self.seen = []

    def name(self):
        return "probe"

    def chat(self, messages, tools=None):
        self.seen.append([dict(m2) for m2 in messages])
        return "完成声明：任务已完成"


def _mk_runner(**cfg_kw):
    cfg = EngineConfig(max_loop_rounds=2, max_unit_budget=2, **cfg_kw)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    llm = ProbeLlm()
    r = Runner(cfg, DomainRegistry(cfg), ws, llm, load_tools(ws))
    return r, llm, ws


def _system_of(llm, idx):
    return next(m["content"] for m in llm.seen[idx] if m["role"] == "system")


def test_system_prompt_contains_policy_line():
    r, llm, ws = _mk_runner(sandbox_enabled=True)
    r.run_unit("U-1", "execute", {"task": "写一个产物", "deliverables": []})
    system = _system_of(llm, 0)
    assert "sandbox: on" in system
    assert "integrity: partial" in system
    assert "network: allowed" in system
    assert str(ws.root) in system


def test_policy_line_off_and_byte_stable():
    r, llm, _ws = _mk_runner(sandbox_enabled=False)
    r.run_unit("U-1", "execute", {"task": "t", "deliverables": []})
    r.run_unit("U-2", "execute", {"task": "t", "deliverables": []})
    s1 = _system_of(llm, 0)
    s2 = _system_of(llm, 1)
    assert s1.endswith("sandbox: off")
    assert s2.endswith("sandbox: off")
    assert s1 == s2, "同状态系统提示必须逐字节一致（KV cache 前缀稳定）"
