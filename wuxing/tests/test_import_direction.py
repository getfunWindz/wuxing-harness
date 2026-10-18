"""骨架分期 P1（F-4）：导入方向守卫。

规则：
- `wuxing/runner.py` 与 `wuxing/context_preview.py` **不得**依赖 `wuxing.engine`
  （反向互引）——共享工具经中性模块（`wuxing.context_window` / `wuxing.session_plan`）；
- 允许方向：engine → runner（组合，保持惰性导入）——不在此守卫生效范围。

口径：AST 全量扫描（顶部与函数内惰性导入均查）。
"""
import ast
import pathlib

FORBIDDEN = ("wuxing/runner.py", "wuxing/context_preview.py")
FORBIDDEN_MODULE = "wuxing.engine"


def _imported_modules(path: pathlib.Path) -> list:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            out.append(node.module)
        elif isinstance(node, ast.Import):
            out += [a.name for a in node.names]
    return out


def test_no_reverse_engine_import():
    root = pathlib.Path(__file__).resolve().parents[2]
    for rel in FORBIDDEN:
        mods = _imported_modules(root / rel)
        bad = [m for m in mods
               if m == FORBIDDEN_MODULE or m.startswith(FORBIDDEN_MODULE + ".")]
        assert not bad, f"{rel} 反向依赖 engine：{bad}"


def test_shared_helpers_live_in_neutral_modules():
    """共享工具落中性模块；engine 侧引用同一来源（单一事实）。"""
    root = pathlib.Path(__file__).resolve().parents[2]
    cw = root / "wuxing" / "context_window.py"
    sp = root / "wuxing" / "session_plan.py"
    assert cw.is_file(), "context_window.py 缺失"
    assert sp.is_file(), "session_plan.py 缺失"
    from wuxing.context_window import resolve_context_window
    from wuxing.session_plan import session_plan
    assert resolve_context_window("deepseek:deepseek-flash") == 1_000_000
    assert callable(session_plan)


def test_mixin_modules_do_not_import_engine():
    """P3：engine_* mixin 模块不得反向 import engine（§5-3 风险纪律防再犯）。"""
    root = pathlib.Path(__file__).resolve().parents[2]
    mixins = sorted((root / "wuxing").glob("engine_*.py"))
    assert mixins, "未找到 engine_* mixin 模块"
    for path in mixins:
        mods = _imported_modules(path)
        bad = [m for m in mods
               if m == FORBIDDEN_MODULE or m.startswith(FORBIDDEN_MODULE + ".")]
        assert not bad, f"{path.name} 反向依赖 engine：{bad}"


def test_runner_modules_do_not_import_engine():
    """P7：runner_* 分模块不得反向 import engine（防环——engine/orchestrator → runner）。"""
    root = pathlib.Path(__file__).resolve().parents[2]
    mod_files = sorted((root / "wuxing").glob("runner_*.py"))
    assert mod_files, "未找到 runner_* 分模块（P7 提取后应存在）"
    for path in mod_files:
        mods = _imported_modules(path)
        bad = [m for m in mods
               if m == FORBIDDEN_MODULE or m.startswith(FORBIDDEN_MODULE + ".")]
        assert not bad, f"{path.name} 反向依赖 engine：{bad}"
