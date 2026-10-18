import pathlib
import tempfile

from wuxing.config import EngineConfig
from wuxing.llm.tool_results import ToolCallResult
from wuxing.registry import DomainRegistry
from wuxing.runner import Runner
from wuxing.tools.builtin import BUILTIN_TOOLS
from wuxing.workspace import Workspace


def _run_with_output(output, domain="plan"):
    class CustomLlm:
        def __init__(self): self.call_count = 0
        def name(self): return "custom"
        def chat(self, messages):
            self.call_count += 1
            return output
    cfg = EngineConfig()
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    r = Runner(cfg, DomainRegistry(cfg), ws, CustomLlm(), BUILTIN_TOOLS(ws))
    return r.run_unit("U-1", domain, {"goal": f"{domain}:x"})

def test_schema_validation_accepts_valid():
    res = _run_with_output("方案：完整方案\n验收标准：ok")
    assert res.status == "ok"
    assert res.artifacts[0].kind == "plan"

def test_json_output_validated_by_schema():
    # LLM 输出 JSON 且符合 output_schema（required=["plan"]）→ 通过
    import json
    data = {"plan": {"steps": ["收集信息"], "acceptance": "完整"}}
    res = _run_with_output(json.dumps(data, ensure_ascii=False))
    assert res.status == "ok"

def test_json_output_schema_invalid_rejected():
    # LLM 输出 JSON 但缺 required 字段 → 契约校验失败（无关键词回退→failed）
    import json
    res = _run_with_output(json.dumps({"foo": "bar"}), domain="verify")
    # verify 关键词"结论"不在 JSON 中，schema 校验失败 → failed
    assert res.status == "failed"

def test_non_json_missing_keyword_fails():
    res = _run_with_output("没有关键词的纯文本", domain="verify")
    assert res.status == "failed"

def test_json_markers_not_overridden_by_schema_fail():
    # 审查发现（docstring 契约 vs 实现）：success_markers 命中应放行——
    # 旧实现：合法 JSON dict 时 schema 结果覆盖 markers 结果（OR 语义破坏）
    # P0 T3 适配：verify 域契约需读物证——输出带 read 工具调用（检查行为）
    r = _run_with_output(ToolCallResult(
        text='{"结论": "通过"}',
        tool_calls=[{"name": "read_dependency",
                     "arguments": {"path": "result.md"}}]),
        domain="verify")
    assert r.status == "ok"
