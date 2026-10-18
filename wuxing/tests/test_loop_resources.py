"""TDD：resources 生态（配置生态面——声明/校验/解析；用户裁决非可去除项）。"""
import pathlib
import tempfile

from wuxing.resources import ResourceError, ResourceRegistry


def _mk():
    wd = pathlib.Path(tempfile.mkdtemp())
    (wd / "data").mkdir()
    (wd / "data" / "input.csv").write_text("a,b\n1,2", encoding="utf-8")
    return wd


def test_resource_declaration_and_resolve():
    """声明解析 + 路径解析（工作区相对）。"""
    wd = _mk()
    reg = ResourceRegistry({
        "input": {"type": "file", "path": "data/input.csv"},
        "datadir": {"type": "dir", "path": "data"},
        "remote": {"type": "url", "path": "https://example.test/api"},
    }, workdir=wd)
    assert reg.resolve("input") == (wd / "data" / "input.csv").resolve()
    assert reg.resolve("datadir") == (wd / "data").resolve()
    assert reg.resolve("remote") == "https://example.test/api"


def test_missing_optional_warns_not_fails():
    """optional 资源缺失：warn（不报错——可运行时创建）。"""
    wd = _mk()
    reg = ResourceRegistry({
        "generated": {"type": "file", "path": "out/report.md", "optional": True},
    }, workdir=wd)
    warns = reg.check()
    assert len(warns) == 1 and "generated" in warns[0], warns


def test_missing_required_raises():
    """非 optional 缺失：ResourceError（配置早报——fail-fast）。"""
    wd = _mk()
    reg = ResourceRegistry({
        "must": {"type": "file", "path": "missing.csv"},
    }, workdir=wd)
    try:
        reg.check()
        assert False, "应抛 ResourceError"
    except ResourceError as e:
        assert "must" in str(e)


def test_malformed_declaration_rejected():
    """畸形声明（未知 type/缺 path）→ 拒绝（校验）。"""
    wd = _mk()
    reg = ResourceRegistry({"bad": {"type": "gadget", "path": "x"}}, workdir=wd)
    try:
        reg.check()
        assert False, "畸形声明应抛"
    except ResourceError as e:
        assert "bad" in str(e)


def test_ok_resources_no_warns():
    """全部存在：check 无 warn（正常路径）。"""
    wd = _mk()
    reg = ResourceRegistry({
        "input": {"type": "file", "path": "data/input.csv"},
        "datadir": {"type": "dir", "path": "data", "optional": True},
    }, workdir=wd)
    assert reg.check() == []
