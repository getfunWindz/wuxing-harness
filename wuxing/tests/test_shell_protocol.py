from wuxing.shell.protocol import SHELL_ALLOWED_IMPORTS, ShellProtocol


def test_shell_protocol_defined():
    # 协议类存在（接口即边界：壳只依赖 run_task(task_text, on_event) 与事件类型）
    assert ShellProtocol is not None
    assert "submit_task" in ShellProtocol.__dict__ or \
           "submit_task" in dir(ShellProtocol)

def test_engine_satisfies_protocol():
    import pathlib
    import tempfile

    from wuxing.engine import Engine
    eng = Engine(workdir=pathlib.Path(tempfile.mkdtemp()), auto_confirm=True)
    # 引擎必须提供壳协议要求的入口（结构性检查）
    assert callable(getattr(eng, "run_task", None))

def test_shell_imports_are_bounded():
    """接口即边界：壳只允许 import 公开契约（engine/events/config_contract）——不摸引擎内部。"""
    import ast
    import pathlib
    p = pathlib.Path(__file__).resolve().parents[2] / "wuxing/shell"
    for f in p.rglob("*.py"):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and \
               node.module.startswith("wuxing."):
                # 允许：公开契约（见 SHELL_ALLOWED_IMPORTS 单一事实来源）+ 壳自身子包
                ok = node.module in SHELL_ALLOWED_IMPORTS or \
                    node.module.startswith("wuxing.shell.")
                assert ok, f"{f.name}: shell 不应 import 引擎内部模块 {node.module}"
