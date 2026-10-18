"""C6：扩展示例包（entry-points 分发示范）——注册面 / 真实 loader 路径 / 分发声明守卫。

示例包位置：docs/examples/extensions/wuxing-demo-extension/
（独立可安装包；不随 harness wheel 打包——发布/开发见其 README）。
"""
import importlib
import json
import pathlib
import re
import types

REPO = pathlib.Path(__file__).resolve().parents[2]
PKG_ROOT = REPO / "docs" / "examples" / "extensions" / "wuxing-demo-extension"
MODULE = "wuxing_demo_extension"


def _demo_module(monkeypatch):
    monkeypatch.syspath_prepend(str(PKG_ROOT))
    importlib.invalidate_caches()
    return importlib.import_module(MODULE)


def test_example_package_registers_surface(tmp_path, monkeypatch):
    """register(api) 面：demo_text_stats 工具（只读/execute）+ 提示词段 + TaskDone 钩子。"""
    from wuxing.extensions import ExtensionAPI
    mod = _demo_module(monkeypatch)
    logs: list = []
    api = ExtensionAPI(workdir=tmp_path, source="wuxing-demo", log_fn=logs.append)
    mod.register(api)
    assert [t.name() for t in api.pending_tools] == ["demo_text_stats"]
    tool = api.pending_tools[0]
    assert tool.permission() == {"read": True}
    assert tool.domains == ("execute",)
    assert api.pending_segments and api.pending_segments[0]["domains"] == ("execute",)
    assert [h[0] for h in api.pending_hooks] == ["TaskDone"]


def test_example_package_loads_via_entry_point_loader(tmp_path, monkeypatch):
    """分发路径：真实 load_extensions（entry-points 分支）→ 提交注册 + 工具可执行。"""
    import wuxing.extensions as ext_mod
    from wuxing.tools.base import ToolRegistry
    mod = _demo_module(monkeypatch)
    fake_ep = types.SimpleNamespace(name="wuxing-demo", load=lambda: mod)
    monkeypatch.setattr(ext_mod, "_entry_points", lambda: [fake_ep])
    reg = ToolRegistry([])
    res = ext_mod.load_extensions(tmp_path, registry=reg)
    assert res.problems == []
    assert [t.name() for t in res.tools] == ["demo_text_stats"]
    assert res.dispatcher.has_hooks() is True
    assert reg.get("demo_text_stats") is not None
    # 工具行为：workspace 内文件统计（lines/words/chars）；workspace 外 → 拒绝
    text = "hello world\n第二行\n"
    (tmp_path / "demo.txt").write_text(text, encoding="utf-8")
    ok = res.tools[0].execute(path="demo.txt")
    assert ok.status == "ok"
    data = json.loads(ok.content)
    assert data["lines"] == 2 and data["words"] == 3 and data["chars"] == len(text)
    bad = res.tools[0].execute(path="../outside.txt")
    assert "error" in json.loads(bad.content)


def test_example_package_pyproject_declares_entry_point():
    """分发声明守卫：pyproject 组/目标与包结构一致（typo 即红）。"""
    text = (PKG_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '[project.entry-points."wuxing.extensions"]' in text
    assert re.search(r'^wuxing-demo\s*=\s*"wuxing_demo_extension"\s*$',
                     text, re.MULTILINE), text
    init = PKG_ROOT / MODULE / "__init__.py"
    assert init.is_file()
    assert "def register(api)" in init.read_text(encoding="utf-8")
    assert (PKG_ROOT / "README.md").is_file()
