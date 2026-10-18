"""E2-4：装配预设组合树 + entry-points 分发 + 引擎生效面。"""
import pathlib
import types

import pytest

from wuxing import presets


@pytest.fixture(autouse=True)
def _isolate_user_presets(tmp_path, monkeypatch):
    monkeypatch.setattr(
        presets, "presets_dir",
        lambda workdir=None, user=False: ((tmp_path / "_no_user")
                                          if user else
                                          pathlib.Path(workdir)
                                          / ".wuxing" / "presets"))


def _ws_preset(tmp_path, name, body):
    d = tmp_path / ".wuxing" / "presets"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.jsonc").write_text(body, encoding="utf-8")


def test_builtin_presets_and_extends():
    allp = presets.load_all(None)
    assert "standard" in allp and "lean" in allp
    r = presets.resolve(None, "lean")
    assert r["chain"] == ["lean", "standard"]
    assert r["resolved"]["tools"][0] == "bash"
    assert "*" in r["resolved"]["extensions"]["disable"]
    assert r["hash"]


def test_workspace_preset_overrides_builtin(tmp_path):
    _ws_preset(tmp_path, "standard", '{"tools": ["bash"]}')
    r = presets.resolve(tmp_path, "standard")
    assert r["resolved"]["tools"] == ["bash"]


def test_cycle_detection(tmp_path):
    _ws_preset(tmp_path, "a", '{"extends": "b"}')
    _ws_preset(tmp_path, "b", '{"extends": "a"}')
    with pytest.raises(ValueError, match="成环"):
        presets.resolve(tmp_path, "a")


def test_unknown_extends_and_name(tmp_path):
    _ws_preset(tmp_path, "a", '{"extends": "nope"}')
    with pytest.raises(ValueError, match="未知"):
        presets.resolve(tmp_path, "a")
    with pytest.raises(ValueError, match="未知预设"):
        presets.resolve(tmp_path, "not-exist")


def test_list_with_state(tmp_path):
    _ws_preset(tmp_path, "broken", '{"extends": "nope"}')
    rows = {p["name"]: p for p in presets.list_with_state(tmp_path)}
    assert rows["standard"]["error"] == ""
    assert rows["standard"]["chain"] == ["standard"]
    assert rows["standard"]["hash"]
    assert "description" in rows["standard"] and "builtin" in rows["standard"]
    assert rows["lean"]["chain"] == ["lean", "standard"]
    assert rows["broken"]["error"]                       # 损坏带原因（可见性）
    assert rows["broken"]["chain"] == []
    assert rows["broken"]["hash"] == ""


def test_session_binding_and_fallback(tmp_path):
    presets.save_session(tmp_path, "conversation-a.jsonl", "lean")
    assert presets.load_session(tmp_path)["conversation-a.jsonl"] == "lean"
    r = presets.resolve_for_session(tmp_path, session="conversation-a.jsonl")
    assert r["name"] == "lean"
    presets.save_session(tmp_path, "conversation-a.jsonl", "")
    r2 = presets.resolve_for_session(tmp_path, session="conversation-a.jsonl")
    assert r2["name"] == "standard"
    # 未知默认名 → 回退 standard（不阻断引擎）
    r3 = presets.resolve_for_session(tmp_path, session="x", default="nope")
    assert r3["name"] == "standard"


def test_engine_preset_disables_extensions(tmp_path):
    from wuxing.config import EngineConfig
    from wuxing.engine import Engine
    _ws_preset(tmp_path, "noext", '{"extensions": {"disable": ["*"]}}')
    ext = tmp_path / ".wuxing" / "extensions"
    ext.mkdir(parents=True)
    (ext / "demo.py").write_text(
        "def register(api):\n"
        "    api.register_tool(name='ext_x', description='d',\n"
        "                      parameters={'type': 'object', 'properties': {}},\n"
        "                      execute=lambda **k: {},\n"
        "                      domains=('execute',), permission={'read': True})\n",
        encoding="utf-8")
    eng = Engine(cfg=EngineConfig(use_real_shape=False,
                                 assembly_preset="noext"),
                 workdir=tmp_path)
    assert eng.preset["name"] == "noext"
    assert eng.tools.get("ext_x") is None


def test_engine_preset_tools_and_segments_and_skills(tmp_path):
    from wuxing.config import EngineConfig
    from wuxing.engine import Engine
    _ws_preset(tmp_path, "tiny",
               '{"tools": ["bash", "read_file"],'
               ' "prompt_segments": {"disable": ["*"]},'
               ' "skills": {"disable": ["*"]}}')
    ext = tmp_path / ".wuxing" / "extensions"
    ext.mkdir(parents=True)
    (ext / "seg.py").write_text(
        "def register(api):\n    api.add_prompt_segment('段')\n",
        encoding="utf-8")
    eng = Engine(cfg=EngineConfig(use_real_shape=False,
                                  assembly_preset="tiny"),
                 workdir=tmp_path)
    assert "bash" in eng.tools._tools
    assert "write_file" not in eng.tools._tools
    assert eng._ext_segments == []
    assert "*" in eng._skills_disabled


def test_assembly_includes_preset_component(tmp_path):
    from wuxing.config import EngineConfig
    from wuxing.engine import Engine
    _ws_preset(tmp_path, "tiny", '{"tools": ["bash"]}')
    e1 = Engine(cfg=EngineConfig(use_real_shape=False), workdir=tmp_path)
    e2 = Engine(cfg=EngineConfig(use_real_shape=False,
                                 assembly_preset="tiny"), workdir=tmp_path)
    assert e1.assembly["components"]["preset"]["name"] == "standard"
    assert e2.assembly["components"]["preset"]["name"] == "tiny"
    assert e1.assembly["id"] != e2.assembly["id"]


def test_entry_point_extension_loaded_and_filterable(tmp_path, monkeypatch):
    from wuxing import extensions as ext
    mod = types.ModuleType("fake_ext")

    def register(api):
        api.register_tool(name="ep_tool", description="d",
                          parameters={"type": "object", "properties": {}},
                          execute=lambda **k: {}, domains=("execute",),
                          permission={"read": True})

    mod.register = register

    class _EP:
        name = "ep-demo"

        def load(self):
            return mod

    monkeypatch.setattr(ext, "_entry_points", lambda: [_EP()])
    nodir = tmp_path / "none"
    res = ext.load_extensions(tmp_path, enabled=True, dirs=[nodir])
    assert any(t.name() == "ep_tool" for t in res.tools)
    res2 = ext.load_extensions(tmp_path, enabled=True, dirs=[nodir],
                               disabled_names=["ep-demo"])
    assert not any(t.name() == "ep_tool" for t in res2.tools)
    res3 = ext.load_extensions(tmp_path, enabled=True, dirs=[nodir],
                               enabled_names=["other"])
    assert not any(t.name() == "ep_tool" for t in res3.tools)
