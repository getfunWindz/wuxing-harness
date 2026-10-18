"""SEC2：扩展分发审查——动态捕获 / 静态扫描 / 风险标注。

设计：docs/WUXING_安全三件套_设计_2026-09-30.md §3（裁决 A）。
"""
import textwrap

from wuxing import ext_audit


def _write_ext(root, name, body):
    pkg = root / name
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text(textwrap.dedent(body), encoding="utf-8")
    return pkg


def test_dynamic_inspection_captures_tools_and_permissions(tmp_path):
    pkg = _write_ext(tmp_path, "safe_ext", '''
        def register(api):
            api.register_tool(name="demo_read", description="读", parameters={},
                              execute=lambda **kw: None,
                              permission={"read": True})
    ''')
    audit = ext_audit.inspect_extension(pkg)
    assert audit.mode == "dynamic"
    names = [t["name"] for t in audit.tools]
    assert names == ["demo_read"]
    perm = dict(audit.tools[0]["permission"])
    assert perm.get("read") and not perm.get("write")
    assert all(f.severity != "danger" for f in ext_audit.risk_flags(audit))


def test_risk_flags_dangerous_permission_and_import(tmp_path):
    pkg = _write_ext(tmp_path, "danger_ext", '''
        import subprocess

        def register(api):
            api.register_tool(name="run_it", description="执行", parameters={},
                              execute=lambda **kw: None,
                              permission={"execute": True, "destructive": True})
    ''')
    audit = ext_audit.inspect_extension(pkg)
    flags = ext_audit.risk_flags(audit)
    kinds = {f.kind for f in flags}
    assert "dangerous-permission" in kinds
    assert "suspicious-import" in kinds
    report = ext_audit.render_report(audit)
    assert "danger_ext" in report and "dangerous-permission" in report


def test_static_mode_does_not_execute(tmp_path):
    pkg = _write_ext(tmp_path, "boom_ext", '''
        def register(api):
            raise RuntimeError("不应被执行")
    ''')
    audit = ext_audit.inspect_extension(pkg, static=True)
    assert audit.mode == "static"
    assert any(str(p).endswith("__init__.py") for p in audit.source_files)


def test_missing_register_raises(tmp_path):
    pkg = _write_ext(tmp_path, "noreg_ext", "X = 1\n")
    try:
        ext_audit.inspect_extension(pkg)
    except ValueError as e:
        assert "register" in str(e)
    else:
        raise AssertionError("缺少 register 应报错")


def test_static_pyproject_entry_points_hint(tmp_path):
    """C3（E0-4/P2-2）：静态模式提示 pyproject entry-points（info——不阻断退出码）。"""
    pkg = _write_ext(tmp_path, "pp_ext", "def register(api):\n    pass\n")
    (pkg / "pyproject.toml").write_text(
        '[project]\nname = "pp-ext"\nversion = "0.1.0"\n'
        '[project.entry-points."wuxing.extensions"]\n'
        'pp = "pp_ext:register"\n', encoding="utf-8")
    audit = ext_audit.inspect_extension(pkg, static=True)
    assert audit.pyproject.endswith("pyproject.toml")
    hit = [f for f in ext_audit.risk_flags(audit)
           if f.kind == "pyproject-entry-points"]
    assert hit and hit[0].severity == "info", hit


def test_static_pyproject_absent_or_plain_no_flag(tmp_path):
    pkg = _write_ext(tmp_path, "no_pp", "def register(api):\n    pass\n")
    audit = ext_audit.inspect_extension(pkg, static=True)
    assert audit.pyproject == ""
    assert not any(f.kind == "pyproject-entry-points"
                   for f in ext_audit.risk_flags(audit))
    plain = _write_ext(tmp_path, "pp_plain", "def register(api):\n    pass\n")
    (plain / "pyproject.toml").write_text(
        '[project]\nname = "x"\n', encoding="utf-8")
    audit2 = ext_audit.inspect_extension(plain, static=True)
    assert not any(f.kind == "pyproject-entry-points"
                   for f in ext_audit.risk_flags(audit2))


def test_static_scan_flags_dangerous_permission_literal(tmp_path):
    """审查修复（2026-09-30）：静态模式须扫描权限字面量（不执行代码的门控面）。

    旧实现 static 只收集 source_files——危险权限声明不可见（exit 0），
    与设计 §3.2/指引「静态扫元数据/字面量」不符。
    """
    pkg = _write_ext(tmp_path, "static_danger", '''
        def register(api):
            api.register_tool(name="x", description="执行", parameters={},
                              execute=lambda **kw: None,
                              permission={"read": True, "execute": True})
    ''')
    audit = ext_audit.inspect_extension(pkg, static=True)
    flags = ext_audit.risk_flags(audit)
    assert any(f.kind == "dangerous-permission-literal"
               and f.severity == "danger" for f in flags), flags


def test_cli_static_dangerous_literal_exit_1(tmp_path, capsys):
    from scripts.check_extension import main
    pkg = _write_ext(tmp_path, "static_danger2", '''
        def register(api):
            api.register_tool(name="x", description="执行", parameters={},
                              execute=lambda **kw: None,
                              permission={"execute": True})
    ''')
    assert main([str(pkg), "--static"]) == 1


def test_static_scan_missing_register_warn(tmp_path):
    pkg = _write_ext(tmp_path, "static_noreg", "X = 1\n")
    audit = ext_audit.inspect_extension(pkg, static=True)
    flags = ext_audit.risk_flags(audit)
    assert any(f.kind == "missing-register" and f.severity == "warn"
               for f in flags), flags


def test_static_literal_scan_no_false_positive_safe(tmp_path):
    pkg = _write_ext(tmp_path, "static_safe", '''
        def register(api):
            api.register_tool(name="r", description="读", parameters={},
                              execute=lambda **kw: None,
                              permission={"read": True})
    ''')
    audit = ext_audit.inspect_extension(pkg, static=True)
    flags = ext_audit.risk_flags(audit)
    assert all(f.severity != "danger" for f in flags), flags
    assert not any(f.kind == "missing-register" for f in flags), flags


def test_cli_json_and_exit_codes(tmp_path, capsys):
    from scripts.check_extension import main
    safe = _write_ext(tmp_path, "cli_safe", '''
        def register(api):
            api.register_tool(name="r", description="读", parameters={},
                              execute=lambda **kw: None, permission={"read": True})
    ''')
    code = main([str(safe), "--json"])
    out = capsys.readouterr().out
    assert code == 0 and '"tools"' in out and '"flags"' in out
    danger = _write_ext(tmp_path, "cli_danger", '''
        def register(api):
            api.register_tool(name="x", description="执行", parameters={},
                              execute=lambda **kw: None, permission={"execute": True})
    ''')
    assert main([str(danger), "--json"]) == 1


def test_cli_static_and_load_error(tmp_path, capsys):
    from scripts.check_extension import main
    boom = _write_ext(tmp_path, "cli_boom", '''
        def register(api):
            raise RuntimeError("不应执行")
    ''')
    assert main([str(boom), "--static"]) == 0   # 静态不执行
    assert main([str(tmp_path / "missing_pkg")]) == 2  # 加载失败


def test_packaging_root_resolves_single_package(tmp_path):
    """打包根（如 docs/examples 的扩展包）——无根 __init__.py，应自动找唯一子包。"""
    _write_ext(tmp_path, "pack_root/inner_ext", '''
        def register(api):
            api.register_tool(name="inner_r", description="读", parameters={},
                              execute=lambda **kw: None, permission={"read": True})
    ''')
    audit = ext_audit.inspect_extension(tmp_path / "pack_root")
    assert audit.mode == "dynamic"
    assert [t["name"] for t in audit.tools] == ["inner_r"]
