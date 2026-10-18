"""TDD：精确测试机械体检（确定性——评审证据基线；不修改工作区）。"""
import pathlib

from wuxing.accuracy import mechanical_checkup


def _mk_tree(tmp_path: pathlib.Path) -> pathlib.Path:
    (tmp_path / "main.py").write_text("print('hello')\n", encoding="utf-8")
    (tmp_path / "broken.py").write_text("def broken(:\n    pass\n", encoding="utf-8")
    (tmp_path / "README.md").write_text(
        "说明\n[中间 120 字符已压缩]\n用法：python main.py\n", encoding="utf-8")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "x.json").write_text('{"a": 1}', encoding="utf-8")
    (tmp_path / ".wuxing").mkdir()
    (tmp_path / ".wuxing" / "trace.jsonl").write_text("{}\n", encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_ok.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8")
    return tmp_path


def test_mechanical_checkup_detects_all(tmp_path):
    out = mechanical_checkup(_mk_tree(tmp_path), probe_timeout=60)
    paths = [f["path"] for f in out["files"]]
    assert "main.py" in paths and "README.md" in paths and "data/x.json" in paths
    assert not any(p.startswith(".wuxing/") for p in paths), "内部目录必须排除"
    assert out["total_files"] == len(out["files"])
    assert out["compressed_markers"] and \
        out["compressed_markers"][0]["path"] == "README.md", out["compressed_markers"]
    errs = [e["path"] for e in out["py_compile"]["errors"]]
    assert "broken.py" in errs and out["py_compile"]["checked"] >= 2
    probes = {p["path"]: p for p in out["run_probes"]}
    assert probes["main.py"]["returncode"] == 0
    assert "hello" in probes["main.py"]["output_head"]
    assert out["tests_probe"] is not None
    assert out["tests_probe"]["returncode"] == 0, out["tests_probe"]


def test_mechanical_checkup_deterministic(tmp_path):
    root = _mk_tree(tmp_path)
    a = mechanical_checkup(root, probe_timeout=60)
    b = mechanical_checkup(root, probe_timeout=60)
    assert a == b, "机械体检必须确定性（无时间戳/无漂移）"


def test_mechanical_checkup_empty_workdir(tmp_path):
    out = mechanical_checkup(tmp_path)
    assert out["total_files"] == 0 and out["run_probes"] == []
    assert out["tests_probe"] is None
