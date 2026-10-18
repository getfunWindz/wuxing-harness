import pathlib
import tempfile

from wuxing.config import EngineConfig
from wuxing.engine import Engine


def test_engine_accepts_custom_llm():
    cfg = EngineConfig()
    eng = Engine(cfg=cfg, workdir=pathlib.Path(tempfile.mkdtemp()), llm=None)
    assert eng.llm.name() == "MockLlmProvider"


def test_real_shape_uses_default_model_adapter(monkeypatch):
    """2026-09-19 用户裁决：真实形状化用【默认模型】（cfg.llm，非域级路由）。

    域级 router 存在时仍用默认 provider（形状化不属于任何域）；适配器委托其 chat。"""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    cfg = EngineConfig(llm="deepseek:deepseek-flash",
                       router={"plan": "deepseek:deepseek-v4-pro"},
                       use_real_shape=True)
    eng = Engine(cfg=cfg, workdir=pathlib.Path(tempfile.mkdtemp()))
    adapter = eng._default_shape_llm()
    assert adapter is not None, "默认模型可用时应构造形状化客户端"
    assert adapter._provider is eng.llm, "必须用默认 provider（不能用 router/域级）"


def test_shape_adapter_delegates_chat():
    """适配器 _chat 委托引擎 provider（任意供应商类型）→ 解析 JSON。"""
    from wuxing.llm.shape_adapter import DefaultModelShapeLlm

    class FakeProvider:
        def __init__(self):
            self.seen = None

        def chat(self, messages, tools=None):
            self.seen = messages
            return type("R", (), {"text": '{"nodes": [], "edges": []}'})()

    provider = FakeProvider()
    llm = DefaultModelShapeLlm(provider, model_name="some-model")
    out = llm._chat([{"role": "user", "content": "hi"}])
    assert out == {"nodes": [], "edges": []}
    assert provider.seen and provider.seen[0]["content"] == "hi"

def test_engine_real_shape_switch_calls_golden_ratio(monkeypatch):
    """真实形状化开关语义（2026-09-18 默认开）：
    False → mock（用户主动关闭，可跑）；
    True 无凭据 → 不再阻断：构造成功 + mock 降级 + 引导提示（降级结果不写 shape 缓存）。"""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    cfg = EngineConfig(use_real_shape=False)
    eng = Engine(cfg=cfg, workdir=pathlib.Path(tempfile.mkdtemp()))
    assert eng._build_fragments("写一篇请假邮件")
    cfg2 = EngineConfig(use_real_shape=True)
    eng2 = Engine(cfg=cfg2, workdir=pathlib.Path(tempfile.mkdtemp()))
    assert eng2._build_fragments("写一篇请假邮件"), "降级 mock 不阻断"
    assert "默认模型不可用" in eng2._shape_notice
    assert "模型与供应商" in eng2._shape_notice
    assert eng2.shape_cache.get("写一篇请假邮件") is None, \
        "降级结果不得写入 shape 缓存（配好凭据后应可重跑真实形状化）"


def test_real_shape_default_model_credential_from_store(monkeypatch, tmp_path):
    """默认模型的凭据来自凭据文档（env > 凭据存储）——形状化适配器持有该 provider。"""
    import json

    from wuxing import credentials as creds

    store = tmp_path / "credentials.json"
    store.write_text(json.dumps(
        {"version": 1, "credentials": {"MY_KEY": "sk-store"}}),
        encoding="utf-8")
    monkeypatch.setattr(creds, "credentials_path", lambda: store)
    monkeypatch.delenv("MY_KEY", raising=False)

    cfg = EngineConfig(
        llm="myprov/some-model",
        providers={"myprov": {"type": "openai",
                             "base_url": "https://example.invalid/v1",
                             "credential_ref": "MY_KEY"}},
        use_real_shape=True)
    eng = Engine(cfg=cfg, workdir=pathlib.Path(tempfile.mkdtemp()))
    adapter = eng._default_shape_llm()
    assert adapter is not None, "凭据文档中的默认模型 key 应被解析"
    assert getattr(adapter._provider, "api_key", "") == "sk-store"
    assert isinstance(eng._shape_notice, str)  # 未跑任务前只校类型（内容断言见下一条用例）


def test_real_shape_no_key_notice_in_report(monkeypatch):
    """无可用默认模型：任务报告必须包含引导提示（配置入口 + 关闭入口）。"""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    eng = Engine(cfg=EngineConfig(use_real_shape=True),
                 workdir=pathlib.Path(tempfile.mkdtemp()), auto_confirm=True)
    res = eng.run_task("写一封请假邮件")
    assert "默认模型不可用" in res.report
    assert "机制调优" in res.report, "提示必须告知关闭入口"


def test_real_shape_success_writes_shape_cache(monkeypatch):
    """真实路径成功时必须写 shape 缓存（与降级路径不写缓存互为守护）。"""
    from types import SimpleNamespace

    import golden_ratio.shape as shape_mod

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")

    node = SimpleNamespace(id="n1", text="步骤", domain_dist={"execute": 1.0},
                           trades=["code"], complexity="low",
                           deliverable="code", color_weight=0.5)
    dag = SimpleNamespace(nodes=[node], edges=[])

    monkeypatch.setattr(shape_mod, "shape_task",
                        lambda text, llm: (dag, None))

    eng = Engine(cfg=EngineConfig(llm="deepseek:deepseek-flash",
                                  use_real_shape=True),
                 workdir=pathlib.Path(tempfile.mkdtemp()))
    assert eng._default_shape_llm() is not None, "默认模型可用（key 已配）"
    eng._shape_or_cached("缓存写入守护任务")
    assert eng.shape_cache.get("缓存写入守护任务") is not None
    assert eng._shape_notice == "", "真实路径不应产生降级提示"
