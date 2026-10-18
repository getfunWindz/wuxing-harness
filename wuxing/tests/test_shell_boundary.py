"""壳边界测试升级（第七轮 + 壳设计 §2）：import 白名单 + 越界属性扫描。

- 新 web 壳代码不得 import 引擎内部模块（白名单：engine/events/shell.protocol）；
- 不得访问引擎内部属性（confirm_gate/reply_cache/orchestrator/...）——只走公开 API；
- 壳代码（web）无豁免——所有文件同标准扫描；
- 扫描器自带自检（合成违规样本必须被捕获）——防「永远通过的假绿守卫」。
"""
import ast
import pathlib

SHELL = pathlib.Path(__file__).resolve().parents[1] / "shell"
from wuxing.shell.protocol import SHELL_ALLOWED_IMPORTS

ALLOWED_MODULES = set(SHELL_ALLOWED_IMPORTS) | {"wuxing.shell.protocol"}
ATTR_BLACKLIST = {"confirm_gate", "reply_cache", "orchestrator", "registry",
                  "brain_memory", "session_pool", "trace", "provenance"}


def _scan_tree(tree: ast.AST) -> tuple:
    """返回违规：([(lineno, module)], [(lineno, attr)])。

    允许：引擎公开面（engine/events/shell.protocol）+ 壳自身子包
    （wuxing.shell.*）——壳内部模块互引不越界。
    """
    import_violations, attr_violations = [], []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module \
                and (node.module == "wuxing" or node.module.startswith("wuxing.")):
            if node.module == "wuxing":
                # 加固（批 4）：`from wuxing import X` 等价于 `wuxing.X`——同标准判定
                for a in node.names:
                    mod = f"wuxing.{a.name}"
                    if mod not in ALLOWED_MODULES \
                            and not mod.startswith("wuxing.shell."):
                        import_violations.append((node.lineno, mod))
                continue
            ok = node.module in ALLOWED_MODULES \
                or node.module.startswith("wuxing.shell.")
            if not ok:
                import_violations.append((node.lineno, node.module))
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.startswith("wuxing.") and \
                        not a.name.startswith("wuxing.shell"):
                    import_violations.append((node.lineno, a.name))
        elif isinstance(node, ast.Attribute) and node.attr in ATTR_BLACKLIST:
            attr_violations.append((node.lineno, node.attr))
    return import_violations, attr_violations


def _iter_shell_files():
    yield from SHELL.rglob("*.py")


def test_scanner_catches_synthetic_violations():
    """守卫自检：合成违规必须被捕获（防假绿守卫）。"""
    bad = ("from wuxing.runner import Runner\n"
           "def f(engine):\n"
           "    engine.confirm_gate.notify('x', True)\n"
           "    return engine.reply_cache.hits\n")
    imp, attr = _scan_tree(ast.parse(bad))
    assert imp, "非法 import 必须被捕获"
    assert attr, "越界属性必须被捕获"
    # 加固（批 4）：兄弟导入形式（from wuxing import X）必须同标准扫描
    imp2, _attr2 = _scan_tree(ast.parse("from wuxing import runner as _r\n"))
    assert imp2, "from wuxing import X 形式必须被捕获"
    imp3, _attr3 = _scan_tree(ast.parse("from wuxing import tickets\n"))
    assert not imp3, "已登记白名单的兄弟导入不得误报"


def test_shell_import_whitelist():
    for f in _iter_shell_files():
        tree = ast.parse(f.read_text(encoding="utf-8"))
        imp, _ = _scan_tree(tree)
        assert not imp, f"{f}: 壳不得 import 引擎内部模块 {imp}"


def test_shell_no_internal_attribute_access():
    for f in _iter_shell_files():
        tree = ast.parse(f.read_text(encoding="utf-8"))
        _, attr = _scan_tree(tree)
        assert not attr, f"{f}: 禁止访问引擎内部属性 {attr}（壳只走公开 API）"
