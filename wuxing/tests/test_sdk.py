"""G4 最小运行时 SDK：隔离装配 + Runtime 门面（设计 2026-09-26）。

覆盖：Task 1（凭据 env-only / 技能用户层哨兵）、Task 2（Engine isolated 装配）、
Task 3（wuxing.sdk 门面）。TDD：先失败测试后实现。
"""
import os
import pathlib

import pytest

# ---------- Task 1：凭据 env-only + 技能用户层哨兵 ----------

@pytest.fixture()
def store(tmp_path, monkeypatch):
    import wuxing.credentials as c
    monkeypatch.setattr(c, "credentials_path",
                        lambda: tmp_path / "credentials.json")
    monkeypatch.delenv("WUXING_TEST_KEY", raising=False)
    return c


def test_resolve_allow_store_false_prefers_env_only(store, monkeypatch):
    store.set("WUXING_TEST_KEY", "sk-store")
    assert store.resolve("WUXING_TEST_KEY") == "sk-store"  # 现行为不变
    # env 缺席 → 拒绝存储层
    assert store.resolve("WUXING_TEST_KEY", allow_store=False) is None
    # env 在 → env-only 照样取 env
    monkeypatch.setenv("WUXING_TEST_KEY", "sk-env")
    assert store.resolve("WUXING_TEST_KEY", allow_store=False) == "sk-env"


def test_create_provider_env_only_credentials(store, monkeypatch):
    from wuxing.llm.factory import create_provider
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    store.set("FAKE_KEY", "sk-store")
    spec = {"type": "deepseek", "model": "m", "credential_ref": "FAKE_KEY"}
    p_isolated = create_provider(spec, allow_stored_credentials=False)
    assert p_isolated.api_key in ("", None)  # 存储层不被读取
    p_store = create_provider(spec, allow_stored_credentials=True)
    assert p_store.api_key == "sk-store"    # 默认路径现行为不变


def test_skill_registry_user_dir_none_skips_user_layer(tmp_path):
    from wuxing.skills import SkillRegistry
    user = tmp_path / "user-skills"
    (user / "u1").mkdir(parents=True)
    (user / "u1" / "SKILL.md").write_text(
        "---\nname: u1\ndescription: 用户层\n---\n正文", encoding="utf-8")
    scanned = SkillRegistry(user_dir=user, project_dir=None, builtin_dir=None)
    assert "u1" in scanned.index()
    skipped = SkillRegistry(user_dir=None, project_dir=None, builtin_dir=None)
    assert skipped.index() == {}


def test_skill_registry_default_still_home_layer():
    from wuxing.skills import SkillRegistry
    reg = SkillRegistry(project_dir=None, builtin_dir=None)
    assert reg.user_dir == (pathlib.Path(os.path.expanduser("~"))
                            / ".wuxing" / "skills")


# ---------- Task 2：Engine isolated 装配 ----------

def test_isolated_does_not_load_file_config(tmp_path, monkeypatch):
    import wuxing.config_loader as cl
    calls = []

    def _trap(workdir):
        calls.append(pathlib.Path(workdir))
        raise AssertionError("isolated 引擎不得调用文件配置装载")

    monkeypatch.setattr(cl, "load_config", _trap)
    from wuxing.engine import Engine
    eng = Engine(workdir=tmp_path / "ws", isolated=True)
    assert calls == []
    assert eng.cfg.llm == "mock"


def test_isolated_tool_set_is_core_five(tmp_path):
    from wuxing.engine import Engine
    eng = Engine(workdir=tmp_path / "ws", isolated=True)
    assert set(eng.tools._tools) == {"bash", "read_file", "write_file",
                                     "write_artifact", "read_dependency"}


def test_isolated_skills_and_brain_off(tmp_path):
    from wuxing.engine import Engine
    eng = Engine(workdir=tmp_path / "ws", isolated=True)
    assert eng.skills.user_dir is None
    assert eng.skills.index() == {}
    assert eng.brain_memory is None
    assert eng.session_pool is None


def test_isolated_ignores_extension_trap(tmp_path):
    import wuxing.extensions as ext
    from wuxing.engine import Engine
    user_dir = ext.user_extensions_dir()
    user_dir.mkdir(parents=True, exist_ok=True)
    (user_dir / "trap.py").write_text(
        "def register(api):\n"
        "    api.register_tool(name='trap_tool', description='trap',\n"
        "                      parameters={'type': 'object', 'properties': {}},\n"
        "                      execute=lambda **kw: {'ok': True},\n"
        "                      domains=('execute',))\n",
        encoding="utf-8")
    eng = Engine(workdir=tmp_path / "ws", isolated=True)
    assert "trap_tool" not in eng.tools._tools
    assert eng._ext_result.summary_note() == ""


def test_isolated_ignores_mcp_config(tmp_path):
    from wuxing.config import EngineConfig
    from wuxing.engine import Engine
    cfg = EngineConfig(mcp_servers=[{"name": "trap",
                                     "command": "wuxing-no-such-cmd"}])
    eng = Engine(cfg=cfg, workdir=tmp_path / "ws", isolated=True)
    assert eng._mcp_cfgs == []


def test_isolated_provider_env_only(tmp_path, store, monkeypatch):
    from wuxing.config import EngineConfig
    from wuxing.engine import Engine
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    store.set("DEEPSEEK_API_KEY", "sk-store")
    eng = Engine(cfg=EngineConfig(llm="deepseek:deepseek-v4-flash"),
                 workdir=tmp_path / "ws", isolated=True)
    assert eng.llm.api_key in ("", None)  # 存储层不被读取
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env")
    eng2 = Engine(cfg=EngineConfig(llm="deepseek:deepseek-v4-flash"),
                  workdir=tmp_path / "ws2", isolated=True)
    assert eng2.llm.api_key == "sk-env"    # env 仍然可用


# ---------- Task 3：SDK 门面 ----------

def test_build_runtime_default_assembly(tmp_path):
    from wuxing.sdk import build_runtime
    rt = build_runtime(workdir=tmp_path / "ws")
    eng = rt.engine
    assert eng.isolated is True
    assert set(eng.tools._tools) == {"bash", "read_file", "write_file",
                                     "write_artifact", "read_dependency"}
    assert eng.skills.index() == {}
    assert eng.brain_memory is None
    assert eng.session_pool is None
    assert rt.workspace == tmp_path / "ws"


def test_build_runtime_tool_names_subset(tmp_path):
    from wuxing.sdk import build_runtime
    rt = build_runtime(workdir=tmp_path / "ws",
                       tool_names=("bash", "read_file"))
    assert set(rt.engine.tools._tools) == {"bash", "read_file"}


def test_build_runtime_tool_names_validation(tmp_path):
    from wuxing.sdk import build_runtime
    with pytest.raises(ValueError):
        build_runtime(workdir=tmp_path / "ws", tool_names=("bash", "nope"))
    with pytest.raises(ValueError):
        build_runtime(workdir=tmp_path / "ws", tool_names=())


def test_build_runtime_config_overrides(tmp_path):
    from wuxing.sdk import build_runtime
    rt = build_runtime(workdir=tmp_path / "ws",
                       config_overrides={"max_loop_rounds": 3})
    assert rt.engine.cfg.max_loop_rounds == 3
    with pytest.raises(ValueError) as ei:
        build_runtime(workdir=tmp_path / "ws",
                      config_overrides={"extension_enabled": True})
    assert "extension_enabled" in str(ei.value)


def test_runtime_run_mock_full_pipeline(tmp_path):
    from wuxing.sdk import build_runtime
    rt = build_runtime(workdir=tmp_path / "ws")
    res = rt.run("写一篇请假邮件")
    assert res.status == "done"
    assert res.task == "写一篇请假邮件"
    assert res.report != ""
    assert isinstance(res.artifacts, tuple)
    assert res.workspace == str(tmp_path / "ws")
    assert res.task_result.status == res.status


def test_runtime_resume_without_state_raises(tmp_path):
    from wuxing.sdk import RuntimeStateError, build_runtime
    rt = build_runtime(workdir=tmp_path / "ws")
    with pytest.raises(RuntimeStateError):
        rt.resume()


def test_runtime_cancel_without_task_returns_false(tmp_path):
    from wuxing.sdk import build_runtime
    rt = build_runtime(workdir=tmp_path / "ws")
    assert rt.cancel() is False


def test_runtime_run_workdir_sandbox(tmp_path):
    from wuxing.sdk import build_runtime
    ws = tmp_path / "ws"
    rt = build_runtime(workdir=ws)
    before = {p for p in tmp_path.rglob("*")}
    res = rt.run("写一篇请假邮件")
    assert res.status == "done"
    after = {p for p in tmp_path.rglob("*")}
    new = after - before
    assert new, "run 应产生落盘"
    assert all(p == ws or ws in p.parents for p in new)
