import pathlib
import tempfile

from wuxing.protocols import Artifact
from wuxing.workspace import Workspace


def test_workspace_write_and_manifest():
    with tempfile.TemporaryDirectory() as tmp:
        ws = Workspace(pathlib.Path(tmp))
        art = ws.write_artifact(Artifact(path="plan.md", kind="plan"),
                                content="# 计划\n1. 步骤")
        assert art.path == "plan.md"
        assert (pathlib.Path(tmp) / "plan.md").exists()
        mani = ws.manifest()
        assert len(mani) == 1
        assert mani[0].producer_unit == ""
        assert mani[0].kind == "plan"

def test_workspace_read_dependency():
    with tempfile.TemporaryDirectory() as tmp:
        ws = Workspace(pathlib.Path(tmp))
        ws.write_artifact(Artifact(path="plan.md", kind="plan"), content="hi")
        assert ws.read("plan.md") == "hi"
        assert ws.read("missing.md") is None

def test_manifest_producer_unit():
    with tempfile.TemporaryDirectory() as tmp:
        ws = Workspace(pathlib.Path(tmp))
        ws.write_artifact(Artifact(path="a.md", kind="code", producer_unit="U-1"), "x")
        m = ws.manifest()
        assert m[0].producer_unit == "U-1"

def test_write_artifact_blocks_path_escape():
    # 审查发现（实弹复现）：write_artifact 路径 ../ 可逃逸工作区写任意文件
    with tempfile.TemporaryDirectory() as tmp:
        ws = Workspace(pathlib.Path(tmp) / "work")
        try:
            ws.write_artifact(Artifact(path="../evil.txt", kind="code"), "PWNED")
            escaped = (pathlib.Path(tmp) / "evil.txt")
            assert not escaped.exists(), "写入已逃逸工作区！"
        except ValueError:
            pass  # 期望抛 ValueError（API 守卫正确）

def test_read_blocks_path_escape():
    # 非工作区文件（相对 ../ 逃逸）读取必须被拒绝
    with tempfile.TemporaryDirectory() as tmp:
        ws = Workspace(pathlib.Path(tmp))
        assert ws.read("../secret.txt") is None
        # 绝对路径同样拒绝
        assert ws.read(str(pathlib.Path(tmp).parent)) is None

def test_manifest_roundtrip_keeps_depends_on_tuple():
    # 审查发现：manifest 序列化往返后 Artifact.depends_on tuple→list 漂移
    with tempfile.TemporaryDirectory() as tmp:
        ws = Workspace(pathlib.Path(tmp))
        ws.write_artifact(Artifact(path="a.md", kind="code",
                                   depends_on=("plan.md",)), "x")
        m = ws.manifest()
        assert m[0].depends_on == ("plan.md",)
        assert isinstance(m[0].depends_on, tuple)


def test_manifest_corrupt_recovery_graceful():
    """A6：manifest.json 损坏（崩溃半写）→ manifest() 返回空清单不崩溃（重建）。"""
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    (ws.root / "manifest.json").write_text("{corrupt json!!", encoding="utf-8")
    assert ws.manifest() == [], "损坏清单必须优雅降级为空清单（不得抛异常）"


def test_manifest_write_atomic_no_tmp_residue():
    """A6：清单写必须原子（tmp+rename）——写后无 .tmp 残留。"""
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    ws.write_artifact(Artifact(path="a.md", kind="result", producer_unit="U1"),
                      "内容A")
    ws.write_artifact(Artifact(path="b.md", kind="result", producer_unit="U2"),
                      "内容B")
    leftovers = list(ws.root.glob("*.tmp")) + list(ws.root.glob("*.json.tmp"))
    assert leftovers == [], f"原子写后不得残留临时文件：{leftovers}"
    mani = ws.manifest()
    assert {a.path for a in mani} == {"a.md", "b.md"}


def test_manifest_replace_permission_error_resilient(monkeypatch=None):
    """真实测试 beginner-1 暴露：os.replace 遇 Windows 文件锁（PermissionError）
    → 产物写入不阻断（manifest 是索引非生命线）+ 重试。"""
    import os as _os
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    # 第一次 replace 抛 PermissionError，第二次成功（重试语义）
    real_replace = _os.replace
    calls = {"n": 0}

    def flaky_replace(src, dst):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError("[WinError 5] 拒绝访问")
        return real_replace(src, dst)

    monkeypatch = __import__("pytest").MonkeyPatch()
    monkeypatch.setattr(_os, "replace", flaky_replace)
    try:
        art = ws.write_artifact(Artifact(path="a.md", kind="result",
                                         producer_unit="U1"), "内容")
        assert art.path == "a.md"
        assert (ws.root / "a.md").read_text(encoding="utf-8") == "内容", \
            "产物写入必须成功（manifest 失败不阻断）"
        assert calls["n"] >= 2, "replace 必须重试"
    finally:
        monkeypatch.undo()


def test_artifact_write_atomic_partial_failure_keeps_old(tmp_path, monkeypatch):
    """B 级修复：产物写必须原子（tmp+replace）——半写失败不得破坏旧内容
    （manifest A6 原子写同源；「文件为真理」前提）。"""
    import pathlib as _pl
    ws = Workspace(tmp_path)
    ws.write_artifact(Artifact(path="a.md", kind="result"), "v1")
    real_write = _pl.Path.write_text

    def _partial(self, data, *a, **kw):
        real_write(self, str(data)[:2], *a, **kw)  # 模拟半写
        raise OSError("disk full")

    monkeypatch.setattr(_pl.Path, "write_text", _partial)
    raised = False
    try:
        ws.write_artifact(Artifact(path="a.md", kind="result"), "v2")
    except OSError:
        raised = True
    finally:
        monkeypatch.setattr(_pl.Path, "write_text", real_write)
    assert raised, "半写失败应上抛 OSError（调用方需要感知）"
    assert (tmp_path / "a.md").read_text(encoding="utf-8") == "v1", \
        "半写失败后旧产物内容必须完好"
    assert not list(tmp_path.glob("*.tmp")), "失败路径不得残留临时文件"


def test_safe_path_internal_case_variant_blocked(tmp_path):
    """2026-09-27 审查：Windows 大小写不敏感——`.WUXING`/`Task_State.json` 等
    变体在目标**尚不存在**时绕过内部守卫（realpath 无法归一不存在路径的大小写，
    随后落盘命中同一实体文件）。"""
    import os

    import pytest
    if os.name != "nt":
        pytest.skip("仅 Windows 大小写不敏感文件系统适用")
    ws = Workspace(tmp_path)
    for bad in (".WUXING/trace.jsonl", "Reply_Cache.json", "Task_State.json",
                "MANIFEST.JSON"):
        try:
            ws._safe_path(bad)
            raise AssertionError(f"大小写变体绕过内部守卫：{bad}")
        except ValueError:
            # 期望 ValueError（守卫拒绝）：不抛则上方 AssertionError
            pass
    # 正常文件不受影响；截断读回例外仍在（大小写变体同样命中真实目录）
    ws._safe_path("notes.txt")
    ok = ws._safe_path(".WUXING/TRUNCATED/readback.txt")
    assert str(ok).endswith("readback.txt")


def test_safe_path_full_access_allows_outside(tmp_path):
    """SEC3：(i)——full-access 放行工作区外写入。"""
    ws = Workspace(tmp_path / "ws", permission_profile="full-access")
    outside = tmp_path / "outside.txt"
    p = ws._safe_path(str(outside))
    assert p.name == "outside.txt"
    assert not str(p).startswith(str(ws.root))


def test_safe_path_workspace_write_blocks_outside(tmp_path):
    ws = Workspace(tmp_path / "ws")
    try:
        ws._safe_path(str(tmp_path / "outside.txt"))
    except ValueError as e:
        assert "escapes" in str(e)
    else:
        raise AssertionError("默认剖面必须拦截工作区外路径")


def test_safe_path_full_access_still_blocks_internal(tmp_path):
    """full-access 不豁免内部数据面保护（设计 §4.1）。"""
    ws = Workspace(tmp_path / "ws", permission_profile="full-access")
    for bad in (".wuxing/trace.jsonl", ".WUXING/trace.jsonl",
                "reply_cache.json"):
        try:
            ws._safe_path(bad)
            raise AssertionError(f"内部数据面被放行：{bad}")
        except ValueError:
            # 期望 ValueError（守卫拒绝）：不抛则上方 AssertionError
            pass


def test_reports_dir_exposed_and_manifest_relocate(tmp_path):
    """2026-10-01 用户裁决：契约报告收纳到 .wuxing/reports/（内部目录但读写可达）。

    manifests 同步重定位（旧路径条目 → 新路径），供 UI/manifest 引用一致。
    """
    from wuxing.protocols import Artifact
    ws = Workspace(tmp_path / "ws")
    ws.write_artifact(Artifact(path="F-1-result.md", kind="result"), "报告")
    assert any(a.path == "F-1-result.md" for a in ws.manifest())
    # 读取 .wuxing/reports 下文件允许（收纳后 read_file/verify 可达）
    p = ws._safe_path(".wuxing/reports/F-1-result.md")
    assert str(p).endswith("F-1-result.md")
    # 其余 .wuxing 内部仍隐藏
    try:
        ws._safe_path(".wuxing/trace.jsonl")
        raise AssertionError(".wuxing/trace.jsonl 仍应隐藏")
    except ValueError:
        # 期望 ValueError（守卫拒绝）：不抛则上方 AssertionError
        pass
    ws.relocate_manifest_path("F-1-result.md", ".wuxing/reports/F-1-result.md")
    paths = [a.path for a in ws.manifest()]
    assert ".wuxing/reports/F-1-result.md" in paths
    assert "F-1-result.md" not in paths
