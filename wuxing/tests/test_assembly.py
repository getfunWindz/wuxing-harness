"""G5 装配代际与失败可视：指纹确定性/敏感性、代际记录、degraded 可见、报告注记。

设计：`docs/WUXING_装配代际与失败可视_G5_设计_2026-09-26.md`。
"""
import json

from wuxing.config import EngineConfig
from wuxing.engine import Engine


def _mk(workdir, **cfg_kw):
    return Engine(cfg=EngineConfig(**cfg_kw), workdir=workdir)


def _record(workdir):
    return json.loads((workdir / ".wuxing" / "assembly.json")
                      .read_text(encoding="utf-8"))


def test_assembly_id_deterministic_same_assembly(tmp_path):
    ws = tmp_path / "ws"
    a = _mk(ws, extension_enabled=False)
    b = _mk(ws, extension_enabled=False)
    assert a.assembly["id"]
    assert a.assembly["id"] == b.assembly["id"]


def test_assembly_id_changes_with_config(tmp_path):
    ws = tmp_path / "ws"
    a = _mk(ws)
    b = _mk(ws, max_loop_rounds=3)
    assert a.assembly["id"] != b.assembly["id"]


def test_assembly_id_changes_with_extension_content(tmp_path):
    ws = tmp_path / "ws"
    ext = ws / ".wuxing" / "extensions"
    ext.mkdir(parents=True)
    f = ext / "demo.py"
    f.write_text("def register(api):\n    pass\n", encoding="utf-8")
    a = _mk(ws)
    f.write_text("def register(api):\n    api.log('v2')\n", encoding="utf-8")
    b = _mk(ws)
    assert a.assembly["id"] != b.assembly["id"]


def test_assembly_id_changes_with_skill_content(tmp_path):
    ws = tmp_path / "ws"
    sk = ws / ".skills" / "s1"
    sk.mkdir(parents=True)
    md = sk / "SKILL.md"
    md.write_text("---\nname: s1\ndescription: d\n---\n甲",
                  encoding="utf-8")
    a = _mk(ws)
    md.write_text("---\nname: s1\ndescription: d\n---\n乙",
                  encoding="utf-8")
    b = _mk(ws)
    assert a.assembly["id"] != b.assembly["id"]


def test_assembly_record_and_previous_id(tmp_path):
    ws = tmp_path / "ws"
    a = _mk(ws)
    rec1 = _record(ws)
    assert rec1["version"] == 1
    assert rec1["id"] == a.assembly["id"]
    assert rec1["previous_id"] is None
    assert rec1["components"]["version"]
    b = _mk(ws, max_loop_rounds=3)
    rec2 = _record(ws)
    assert rec2["id"] == b.assembly["id"]
    assert rec2["previous_id"] == rec1["id"]
    _mk(ws, max_loop_rounds=3)  # 同代再现
    rec3 = _record(ws)
    assert rec3["id"] == rec2["id"]
    assert rec3["previous_id"] == rec1["id"]  # 同代不刷新


def test_assembly_degraded_broken_extension(tmp_path):
    ws = tmp_path / "ws"
    ext = ws / ".wuxing" / "extensions"
    ext.mkdir(parents=True)
    (ext / "broken.py").write_text(
        "def register(api):\n    raise RuntimeError('坏扩展')\n",
        encoding="utf-8")
    e = _mk(ws)
    deg = e.assembly["degraded"]
    assert len(deg) == 1
    assert deg[0]["component"] == "extensions"
    assert deg[0]["name"] == "broken"
    assert "坏扩展" in deg[0]["reason"]


def test_assembly_report_note_with_degraded(tmp_path):
    ws = tmp_path / "ws"
    ext = ws / ".wuxing" / "extensions"
    ext.mkdir(parents=True)
    (ext / "broken.py").write_text(
        "def register(api):\n    raise RuntimeError('坏扩展')\n",
        encoding="utf-8")
    e = _mk(ws)
    res = e.run_task("写一篇请假邮件")
    assert res.status == "done"
    assert "[装配] id=" in res.report
    assert "[装配降级]" in res.report


def test_assembly_trace_event(tmp_path):
    ws = tmp_path / "ws"
    e = _mk(ws)
    lines = [json.loads(x) for x in
             (ws / ".wuxing" / "trace.jsonl").read_text(encoding="utf-8")
             .splitlines() if x.strip()]
    events = [ln for ln in lines if ln.get("event") == "assembly"]
    assert events
    assert events[-1]["id"] == e.assembly["id"]


# ---------- Task 2：壳诊断摘要 ----------

def test_manager_assemblies_summary(tmp_path):
    from wuxing.shell.web.manager import EngineManager

    def _factory(workdir, auto_confirm):
        return Engine(cfg=EngineConfig(), workdir=workdir,
                      auto_confirm=auto_confirm)

    mgr = EngineManager(engine_factory=_factory)
    (tmp_path / "ws").mkdir()
    ws = mgr.open_workspace(str(tmp_path / "ws"))["id"]
    eng = mgr.engine_for(ws)
    out = mgr.assemblies_summary()
    assert len(out) == 1
    assert out[0]["workspace_id"] == ws
    assert out[0]["id"] == eng.assembly["id"]
    assert out[0]["path"] == str(eng.workdir)
    assert out[0]["degraded"] == []


def test_manager_assemblies_summary_skips_engine_without_assembly(tmp_path):
    from wuxing.shell.web.manager import EngineManager

    class _Fake:
        def __init__(self, workdir, auto_confirm=False):
            self.workdir = workdir

    mgr = EngineManager(engine_factory=_Fake)
    (tmp_path / "ws").mkdir()
    ws = mgr.open_workspace(str(tmp_path / "ws"))["id"]
    mgr.engine_for(ws)
    assert mgr.assemblies_summary() == []


def test_assembly_id_changes_with_permission_profile(tmp_path):
    """SEC3：剖面进入装配指纹（config 面——G5 代际可见）。"""
    ws = tmp_path / "ws"
    a = _mk(ws, extension_enabled=False)
    b = _mk(ws, extension_enabled=False, permission_profile="read-only")
    assert a.assembly["id"] != b.assembly["id"]


def test_engine_read_only_filters_mutating_tools(tmp_path):
    """SEC3：引擎装配按剖面过滤（read-only 无 bash/写工具）。"""
    eng = _mk(tmp_path / "ws", extension_enabled=False,
              permission_profile="read-only")
    names = set(eng.tools._tools)
    assert "read_file" in names
    assert "bash" not in names and "write_artifact" not in names


def test_engine_full_access_workspace_paths(tmp_path):
    """SEC3：(i)——full-access 下 Workspace 放行工作区外路径。"""
    eng = _mk(tmp_path / "ws", extension_enabled=False,
              permission_profile="full-access")
    outside = tmp_path / "outside.txt"
    p = eng.ws._safe_path(str(outside))
    assert p.name == "outside.txt"
    assert not str(p).startswith(str(eng.ws.root))


def test_engine_read_only_excludes_late_registered_tools(tmp_path):
    """SEC3 修复（golden 自测发现 2026-09-30）：策略必须覆盖**晚注册**工具。

    旧序：apply_tool_policy（初始工具）→ delegate/设计工具/扩展注册——
    晚注册工具逃逸 read-only 过滤（实测：read-only 下 delegate 可用且空烧预算）。
    """
    eng = _mk(tmp_path / "ws", extension_enabled=False,
              permission_profile="read-only")
    names = set(eng.tools._tools)
    assert "delegate" not in names, sorted(names)
    assert not (names & {"write_map", "write_spec", "unclaim_ticket"}), \
        sorted(names)
    # 强不变量：read-only 装配面必须全部为只读工具
    for t in eng.tools._tools.values():
        perm = dict(t.permission() or {})
        assert perm.get("read") and not any(
            perm.get(k) for k in ("write", "execute", "network", "destructive")
        ), t.name()


def test_engine_read_only_filters_late_registered_extension_tools(tmp_path):
    """扩展工具（装配期晚注册）同样不得逃逸 read-only 过滤。"""
    ext_dir = tmp_path / "exts"
    ext_dir.mkdir()
    (ext_dir / "writer_ext.py").write_text(
        "def register(api):\n"
        "    api.register_tool(name='ext_writer', description='w',\n"
        "                      parameters={}, execute=lambda **kw: 'x',\n"
        "                      domains=('execute',),\n"
        "                      permission={'read': True, 'write': True})\n",
        encoding="utf-8")
    eng = _mk(tmp_path / "ws", extension_enabled=True,
              extension_dirs=[str(ext_dir)], permission_profile="read-only")
    assert "ext_writer" not in eng.tools._tools
    eng2 = _mk(tmp_path / "ws2", extension_enabled=True,
               extension_dirs=[str(ext_dir)],
               permission_profile="workspace-write")
    assert "ext_writer" in eng2.tools._tools
