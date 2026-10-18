import pathlib
import tempfile

from wuxing.config import EngineConfig
from wuxing.registry import DomainRegistry
from wuxing.runner import Runner
from wuxing.tools.builtin import BUILTIN_TOOLS
from wuxing.workspace import Workspace


def _run_with_output(output, domain="user"):
    class CustomLlm:
        def __init__(self): self.call_count = 0
        def name(self): return "custom"
        def chat(self, messages, tools=None):
            self.call_count += 1
            return output
    cfg = EngineConfig()
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    reg = DomainRegistry(cfg)
    if domain == "user":
        reg.activate(["user"])  # 条件域：测试模拟任务启用场景
    r = Runner(cfg, reg, ws, CustomLlm(), BUILTIN_TOOLS(ws))
    return r.run_unit("U-1", domain, {"goal": f"{domain}:x"})

def test_user_domain_contract_converges():
    # user 域（真 LLM 冒烟暴露：无契约 → 3 轮预算耗尽 → failed）
    res = _run_with_output("从用户视角定义验收标准：登录流程顺畅、安全可靠", "user")
    assert res.status == "ok"
    assert res.artifacts[0].kind == "acceptance"

def test_user_domain_missing_markers_fails():
    res = _run_with_output("这是一段不相关的内容", "user")
    assert res.status == "failed"

def test_all_domains_have_contract():
    # 每个域契约必须定义 success_markers（不允许缺域）
    reg = DomainRegistry(EngineConfig())
    for did in reg.all_domain_ids():
        if reg.is_conditional(did):
            reg.activate([did])
        d = reg.get(did)
        assert d.success_markers, f"{did} 域缺少 success_markers"
        assert d.artifact_kind, f"{did} 域缺少 artifact_kind"
