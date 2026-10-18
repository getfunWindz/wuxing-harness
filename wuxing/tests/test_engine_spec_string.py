"""TDD · L4 冒烟发现：Engine.llm 参数须规范化——spec 字符串 → 工厂装配（此前被当 provider 直用）。"""
import pathlib
import tempfile

from wuxing.config import EngineConfig
from wuxing.engine import Engine


def test_llm_spec_string_created_via_factory():
    """llm=\"deepseek:deepseek-chat\"（CLI/评测入口语义）→ provider 实例。"""
    eng = Engine(cfg=EngineConfig(), workdir=pathlib.Path(tempfile.mkdtemp()),
                 llm="deepseek:deepseek-chat")
    assert hasattr(eng.llm, "name"), "spec 字符串必须经工厂转 provider（此前 AttributeError）"
    assert "deepseek" in eng.llm.name()


def test_llm_provider_instance_unchanged():
    """provider 实例直传（测试注入路径）零变化。"""
    from wuxing.llm.mock import MockLlmProvider
    m = MockLlmProvider()
    eng = Engine(cfg=EngineConfig(), workdir=pathlib.Path(tempfile.mkdtemp()), llm=m)
    assert eng.llm is m


def test_llm_dict_spec_created_via_factory():
    """llm=dict spec（智谱 GLM 等 base_url 表达）→ provider 实例。"""
    eng = Engine(cfg=EngineConfig(), workdir=pathlib.Path(tempfile.mkdtemp()),
                 llm={"type": "openai", "model": "glm-5.3-flash",
                      "base_url": "https://open.bigmodel.cn/api/paas/v4",
                      "api_key_env": "NONEXIST_KEY"})
    assert hasattr(eng.llm, "name")
    assert eng.llm.model == "glm-5.3-flash"
