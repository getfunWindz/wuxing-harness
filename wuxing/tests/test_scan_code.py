"""Q4（第二轮计划 §1）：scan_code 死代码降噪——__all__/dunder/字符串引用/白名单。

fixture 驱动（临时工作区写最小 Python 模块，断言候选集合）。
"""
import pathlib

from scripts.scan_code import scan_dead_code


def _write(root: pathlib.Path, rel: str, src: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(src, encoding="utf-8")


def test_basic_dead_candidate(tmp_path):
    _write(tmp_path, "mod.py",
           "def never_used():\n    return 1\n\n\n"
           "def used():\n    return 2\n\n\nused()\n")
    names = [c[0] for c in scan_dead_code(tmp_path)]
    assert "never_used" in names and "used" not in names


def test_dunder_excluded(tmp_path):
    _write(tmp_path, "mod.py",
           "class A:\n    def __init__(self):\n        pass\n\n"
           "    def __repr__(self):\n        return 'A'\n")
    names = [c[0] for c in scan_dead_code(tmp_path)]
    assert "__init__" not in names and "__repr__" not in names


def test_all_export_excluded(tmp_path):
    _write(tmp_path, "mod.py",
           '__all__ = ["public_fn"]\n\n\ndef public_fn():\n    return 1\n')
    names = [c[0] for c in scan_dead_code(tmp_path)]
    assert "public_fn" not in names


def test_string_reference_counts_as_use(tmp_path):
    """按名引用（getattr/注册表/回调声明）——字符串字面量视为引用（降误报）。"""
    _write(tmp_path, "mod.py",
           'def cb():\n    return 1\n\n\n'
           'REG = getattr(object(), "cb")\n')
    names = [c[0] for c in scan_dead_code(tmp_path)]
    assert "cb" not in names


def test_extra_whitelist(tmp_path):
    _write(tmp_path, "mod.py", "def hook():\n    return 1\n")
    assert [c[0] for c in scan_dead_code(tmp_path)] == ["hook"]
    assert scan_dead_code(tmp_path, extra_whitelist={"hook"}) == []


def test_ref_roots_module_qualified_call_counts(tmp_path):
    """D2（E0-5/P3-8）：ref_roots 中的模块限定调用（ext.fn()）计入引用。"""
    root = tmp_path / "wuxing"
    _write(root, "mod.py", "def solo():\n    return 1\n")
    scripts = tmp_path / "scripts"
    _write(scripts, "cli.py",
           "from wuxing import mod\n\n\ndef main():\n    return mod.solo()\n")
    assert [c[0] for c in scan_dead_code(root)] == ["solo"]   # 引用面外 → 候选
    assert scan_dead_code(root, ref_roots=[scripts]) == []    # 纳入引用源 → 非候选


def test_test_reference_counts(tmp_path):
    """D2：root 内测试文件的引用也计入（只作引用源——不产生候选）。"""
    root = tmp_path / "pkg"
    _write(root, "mod.py", "def only_tested():\n    return 1\n")
    _write(root, "tests/test_mod.py",
           "from pkg import mod\n\n\ndef test_x():\n"
           "    assert mod.only_tested() == 1\n")
    assert scan_dead_code(root) == []


def test_reviewed_intentional_api_whitelisted(tmp_path):
    """已核对意向接口（用户预留/框架回调）不产出候选（2026-10-03 辨别结论）。"""
    from scripts.scan_code import _REVIEWED_INTENTIONAL
    _write(tmp_path, "mod.py",
           "def log_message(self, *a):\n    pass\n\n\n"
           "def for_unit(self, x):\n    return x\n")
    assert scan_dead_code(tmp_path)          # 未白名单 → 候选
    assert scan_dead_code(tmp_path,
                          extra_whitelist=_REVIEWED_INTENTIONAL) == []


def test_import_from_counts_as_reference(tmp_path):
    """D2 补盲区：`from ... import 名称`（含 as 别名）视为引用（导入即使用）。"""
    root = tmp_path / "pkg"
    _write(root, "mod.py", "def api():\n    return 1\n")
    _write(root, "tests/test_mod.py",
           "from pkg.mod import api as a\n\n\ndef test_x():\n"
           "    assert a() == 1\n")
    assert scan_dead_code(root) == []


def test_ref_roots_dedup_no_double_count(tmp_path):
    """D2：ref_roots 重复/与 root 重叠时引用只计一次（集合去重）。"""
    root = tmp_path / "wuxing"
    _write(root, "mod.py", "def solo():\n    return 1\n")
    scripts = tmp_path / "scripts"
    _write(scripts, "cli.py",
           "from wuxing import mod\n\n\ndef main():\n    return mod.solo()\n")
    # 一次引用；max_refs=1 → 应为候选（若重复计入为 2 则不候选）
    got = scan_dead_code(root, ref_roots=[scripts, scripts], max_refs=1)
    assert [c[0] for c in got] == ["solo"]
