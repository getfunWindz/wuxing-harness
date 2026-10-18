from wuxing.protocols import DomainDefinition, LlmProvider, UnitResult


def test_domain_definition_shape():
    d = DomainDefinition(
        domain_id="execute",
        title="执行域",
        input_schema={"type": "object", "required": ["goal"]},
        output_schema={"type": "object", "required": ["artifact"]},
        tool_whitelist=("write_artifact",),
        quality_notes="产物必须符合输出schema",
        prompt_skeleton="你是执行域智能体，任务：{goal}",
    )
    assert d.tool_whitelist == ("write_artifact",)
    assert "执行域" in d.prompt_skeleton

def test_unit_result_defaults():
    r = UnitResult(unit_id="U-1", domain_id="execute", status="ok")
    assert r.artifacts == []
    assert r.logs == []

def test_protocols_are_abstract():
    class _Dummy(LlmProvider):
        def chat(self, messages): raise NotImplementedError
        def name(self): return "dummy"
    assert _Dummy().name() == "dummy"
