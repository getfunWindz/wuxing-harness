import pathlib
import tempfile

from wuxing.config import EngineConfig
from wuxing.llm.brain import BrainMemory
from wuxing.registry import DomainRegistry
from wuxing.runner import Runner
from wuxing.tools.builtin import BUILTIN_TOOLS
from wuxing.workspace import Workspace


class OkLlm:
    def name(self): return "ok"
    def chat(self, messages, tools=None):
        return "方案：完整计划"

class FailContractLlm:
    def name(self): return "bad"
    def chat(self, messages, tools=None):
        return "完全不相关的内容"

def test_ok_writes_success_case():
    mem = BrainMemory(pathlib.Path(tempfile.mkdtemp()) / "b.json")
    cfg = EngineConfig()
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    r = Runner(cfg, DomainRegistry(cfg), ws, OkLlm(), BUILTIN_TOOLS(ws),
               brain_memory=mem)
    r.run_unit("U-1", "plan", {"goal": "plan:x"})
    assert len(mem.cases) == 1
    assert mem.cases[0]["success"] is True
    assert mem.cases[0]["domain"] == "plan"

def test_contract_failure_attributed_to_model():
    mem = BrainMemory(pathlib.Path(tempfile.mkdtemp()) / "b.json")
    cfg = EngineConfig()
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    r = Runner(cfg, DomainRegistry(cfg), ws, FailContractLlm(), BUILTIN_TOOLS(ws),
               brain_memory=mem)
    res = r.run_unit("U-1", "plan", {"goal": "plan:x"})
    assert res.status == "failed"
    assert len(mem.cases) == 1
    assert mem.cases[0]["success"] is False  # contract 归因模型


class FailProviderLlm:
    def name(self): return "openai-compat:mimo-v2.5"
    def chat(self, messages, tools=None):
        raise RuntimeError("HTTP 401 Unauthorized")


def test_provider_failure_trace_records_model_and_no_brain_case():
    """第七轮审查（run-2 观测缺口）：provider 失败必须落 trace（含模型标注），
    且不写 brain 案例（归因纪律 §15.4）。

    run-2 实测：4 次 provider 失败仅 1 次可归因（无模型标注）——
    本测试锁定「失败模型可归因」的观测契约。
    """
    import json

    from wuxing.trace import TraceLogger
    mem = BrainMemory(pathlib.Path(tempfile.mkdtemp()) / "b.json")
    cfg = EngineConfig()
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    trace_path = ws.root / "trace.jsonl"
    r = Runner(cfg, DomainRegistry(cfg), ws, FailProviderLlm(),
               BUILTIN_TOOLS(ws), brain_memory=mem,
               trace=TraceLogger(trace_path))
    res = r.run_unit("U-1", "plan", {"goal": "plan:x"})
    assert res.status == "failed"
    assert str(res.error).startswith("provider:"), res.error
    evs = [json.loads(ln) for ln in
           trace_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    done = [e for e in evs if e.get("event") == "unit_done"]
    assert done, "provider 失败必须留 trace 尾（评测原料）"
    ev = done[-1]
    assert ev.get("provider_error") is True
    assert ev.get("model") == "openai-compat:mimo-v2.5", \
        "失败模型必须可归因（观测缺口修复）"
    assert len(mem.cases) == 0, "provider 失败不得写 brain 案例（归因纪律）"
