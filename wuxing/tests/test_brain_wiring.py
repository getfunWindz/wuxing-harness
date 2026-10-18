"""智脑接线测试（D1 前置修复：spec 回构 / 候选路由 / fragment_key 全链）。"""
import pathlib
import tempfile

from wuxing.llm.factory import create_provider


def test_spec_roundtrip_all_providers():
    """spec() → create_provider 回构闭合：同配置 provider 可重建。"""
    for spec in ["deepseek:deepseek-chat", "openai:gpt-4o",
                 "anthropic:claude-sonnet-4-5", "mock"]:
        p = create_provider(spec)
        p2 = create_provider(p.spec())
        assert p2.name() == p.name(), f"{spec}: {p.name()} != {p2.name()}"


def test_responses_provider_spec_roundtrip(monkeypatch):
    """2026-10-01 壳端复验 P1：Responses 适配器必须实现 spec()。

    缺 spec() → 基类回退 name()（'openai-responses:…'）→ 记入智脑记忆 →
    下一个任务 create_provider 回构「未知 provider type」→ 任务失败。
    """
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    p = create_provider({"type": "responses", "model": "deepseek-flash",
                         "base_url": "https://api.deepseek.com"})
    spec = p.spec()
    p2 = create_provider(spec)          # 不得抛 ValueError
    assert p2.name() == p.name()
    assert p2.base_url == "https://api.deepseek.com"


def test_responses_spec_preserves_credential_ref(tmp_path, monkeypatch):
    """2026-10-01 真机 P1：spec() 回构必须保留凭据引用。

    dict spec（自定义 base_url）缺少 credential_ref → 回构时 derive_ref('responses')
    指向 RESPONSES_API_KEY → 找不到 key → RuntimeError『未配置 OPENAI_API_KEY』→
    智脑命中该记忆的任务全部失败（用户循迹模式阻断）。"""
    import wuxing.credentials as creds
    monkeypatch.setattr(creds, "credentials_path", lambda: tmp_path / "c.json")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    creds.set("DEEPSEEK_API_KEY", "sk-ref")
    p = create_provider({"type": "responses", "model": "deepseek-flash",
                         "base_url": "https://api.deepseek.com",
                         "credential_ref": "DEEPSEEK_API_KEY"})
    assert p.api_key == "sk-ref"
    spec = p.spec()
    assert isinstance(spec, dict) and spec.get("credential_ref") == "DEEPSEEK_API_KEY"
    p2 = create_provider(spec)          # 回构不得丢凭据
    assert p2.api_key == "sk-ref"
    assert p2.name() == p.name()


def test_responses_spec_default_base_is_short_form(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    p = create_provider({"type": "responses", "model": "gpt-5"})
    assert p.spec() == "responses:gpt-5"
    p2 = create_provider(p.spec())
    assert p2.name() == p.name()


def test_openai_spec_not_old_compat_name():
    """审查 D1c：旧 llm.name() 返回 openai-compat:gpt-4o——factory 无法回构。"""
    p = create_provider("openai:gpt-4o")  # factory 路径（规范默认 base=api.openai.com/v1）
    assert p.spec() == "openai:gpt-4o"
    assert create_provider(p.spec()).name() == "openai-compat:gpt-4o"


def test_deepseek_spec_preserves_model():
    from wuxing.llm.deepseek import DeepSeekLlmProvider
    p = DeepSeekLlmProvider(model="deepseek-chat")
    assert p.spec() == "deepseek:deepseek-chat"


def test_toolcall_spec_unwraps_inner():
    from wuxing.llm.tool_client import ToolCallingLlm

    class FakeInner:
        def name(self): return "deepseek:deepseek-chat"
        def spec(self): return "deepseek:deepseek-chat"

    tc = ToolCallingLlm(FakeInner(), list)
    assert tc.spec() == "deepseek:deepseek-chat"  # 剥壳：toolcall 前缀不可回构


def test_engine_passes_fragment_key_through():
    """端到端（D1a）：Runner 的 llm_for 拿到碎片文本作 fragment_key。"""
    from wuxing.config import EngineConfig
    from wuxing.engine import Engine

    captured = {}

    class TrackingRouter:
        def for_domain(self, domain_id, fragment_key=None, candidate_index=0):
            captured["key"] = fragment_key
            captured["candidate"] = candidate_index
            return create_provider("mock")

        def candidate_count(self, domain_id):
            return 1  # S1-A/L2：候选感知接口（测试桩同步）

    eng = Engine(cfg=EngineConfig(),
                 workdir=pathlib.Path(tempfile.mkdtemp()),
                 router=TrackingRouter())
    eng.run_task("写一篇请假邮件 方案")
    assert captured.get("key") is not None  # fragment_key 已接线
    assert len(captured["key"]) > 0


def test_runner_records_fragment_text_and_spec():
    """D1b/D1c：record key=碎片文本（跨任务可检索）+ spec 入库（可回构）。"""
    from wuxing.config import EngineConfig
    from wuxing.llm.brain import BrainMemory
    from wuxing.registry import DomainRegistry
    from wuxing.runner import Runner
    from wuxing.tools.builtin import BUILTIN_TOOLS
    from wuxing.workspace import Workspace

    mem = BrainMemory(pathlib.Path(tempfile.mkdtemp()) / "b.json")
    cfg = EngineConfig()
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    r = Runner(cfg, DomainRegistry(cfg), ws, create_provider("mock"),
               BUILTIN_TOOLS(ws), brain_memory=mem)
    r.run_unit("U-1", "plan", {"goal": "plan:x",
                                "fragment_key": "验证 测试 回归"})
    assert len(mem.cases) == 1
    assert mem.cases[0]["key"] == "验证 测试 回归"  # 碎片文本（非 unit_id）
    assert mem.cases[0]["spec"] == "mock"          # spec 入库
    assert mem.cases[0]["model"] == "MockLlmProvider"  # 旧字段兼容（name）


def test_brain_record_stores_spec_for_roundtrip():
    """BrainMemory.record 支持 spec 字段（search 结果携带）。"""
    from wuxing.llm.brain import BrainMemory

    mem = BrainMemory(pathlib.Path(tempfile.mkdtemp()) / "b.json")
    mem.record(key="验证|测试", domain="verify", model="openai-compat:gpt-4o",
               success=True, spec="openai:gpt-4o")
    hits = mem.search("验证 测试")
    assert hits[0]["spec"] == "openai:gpt-4o"
    assert hits[0]["model"] == "openai-compat:gpt-4o"


def test_spec_roundtrip_custom_base_url():
    """中转站场景（micuapi 等）：base_url 非默认 → spec 必须保留 base_url（dict 形式）。"""
    p = create_provider({"type": "anthropic", "model": "claude-sonnet-5",
                         "base_url": "https://www.micuapi.ai"})
    p2 = create_provider(p.spec())
    assert p2.base_url == "https://www.micuapi.ai"
    assert p2.model == "claude-sonnet-5"

    p3 = create_provider({"type": "openai", "model": "gpt-5.6-luna",
                          "base_url": "https://www.micuapi.ai/v1"})
    p4 = create_provider(p3.spec())
    assert p4.base_url == "https://www.micuapi.ai/v1"
    assert p4.model == "gpt-5.6-luna"

    p5 = create_provider({"type": "deepseek", "model": "deepseek-chat",
                          "base_url": "https://www.micuapi.ai/v1"})
    p6 = create_provider(p5.spec())
    assert p6.base_url == "https://www.micuapi.ai/v1"


def test_spec_api_key_env_not_leaked_into_spec(monkeypatch):
    """api_key_env 字段：key 从环境读取，且 spec 不泄露明文 key（config 面安全）。"""
    monkeypatch.setenv("GLM_API_KEY", "sk-test-glm-123")
    p = create_provider({"type": "openai", "model": "glm-5.3-flash",
                         "base_url": "https://www.micuapi.ai/v1",
                         "api_key_env": "GLM_API_KEY"})
    assert p.api_key == "sk-test-glm-123"  # 从环境读取
    spec = p.spec()
    assert "sk-test-glm-123" not in str(spec)  # spec 不含明文 key


def test_spec_api_key_env_shared_spec():
    """多通道 key 互不串扰：各 spec 可声明自己的 api_key_env。"""
    import os
    os.environ["GLM_API_KEY"] = "sk-glm"
    os.environ["KIMI_API_KEY"] = "sk-kimi"
    p1 = create_provider({"type": "openai", "model": "glm-5.3-flash",
                          "base_url": "https://www.micuapi.ai/v1",
                          "api_key_env": "GLM_API_KEY"})
    p2 = create_provider({"type": "openai", "model": "kimi-k2.7-code",
                          "base_url": "https://www.micuapi.ai/v1",
                          "api_key_env": "KIMI_API_KEY"})
    assert p1.api_key == "sk-glm"
    assert p2.api_key == "sk-kimi"


def test_spec_headers_passed_to_provider():
    """micuapi 外接网关：spec 可带自定义 headers（User-Agent 等）——sink 到请求。"""
    seen = {}
    class FakeHttp:
        def post(self, url, **kw):
            seen["headers"] = kw.get("headers", {})
            class R:
                status_code = 200
                def raise_for_status(self): pass
                def json(self): return {"choices": [{"message": {"content": "ok"}}]}
            return R()
    p = create_provider({"type": "openai", "model": "glm-5.3-flash",
                         "base_url": "https://www.micuapi.ai/v1",
                         "api_key_env": "GLM_API_KEY",
                         "headers": {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}})
    p._http = FakeHttp()
    p.chat([{"role": "user", "content": "hi"}])
    assert seen["headers"]["User-Agent"].startswith("Mozilla/5.0")
    assert seen["headers"]["Authorization"].startswith("Bearer ")


def test_temperature_ommitted_when_none():
    """kimi 类模型拒绝 temperature 字段（400）——spec 可配置 temperature=None 省略。"""
    seen = {}
    class FakeHttp:
        def post(self, url, **kw):
            seen["json"] = kw.get("json", {})
            class R:
                status_code = 200
                def raise_for_status(self): pass
                def json(self): return {"choices": [{"message": {"content": "ok"}}]}
            return R()
    p = create_provider({"type": "openai", "model": "kimi-k2.7-code",
                         "base_url": "https://www.micuapi.ai/v1",
                         "api_key_env": "KIMI_API_KEY", "temperature": None})
    p._http = FakeHttp()
    p.chat([{"role": "user", "content": "hi"}])
    assert "temperature" not in seen["json"]  # 省略字段

    p2 = create_provider({"type": "openai", "model": "gpt-5.6-luna",
                          "base_url": "https://www.micuapi.ai/v1", "temperature": 0.0})
    p2._http = FakeHttp()
    p2.chat([{"role": "user", "content": "hi"}])
    assert seen["json"]["temperature"] == 0.0  # 显式 0 正常发送
