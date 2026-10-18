"""静默异常守卫（质量清理批 F-5 · 2026-10-02）。

约定：异常处理块若为「静默回退」（handler 体仅 pass / return 常量 / 常量表达式），
必须在处理块内注释说明理由（或降级日志）——控制排障成本。
来源：docs/WUXING_代码质量审查_2026-10-02.md（F-5 静默异常注释批）。
"""
import ast
import io
import pathlib
import tokenize

WUXING_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _is_silent_stmt(stmt: ast.stmt) -> bool:
    """handler 体语句是否属「静默」形态（pass / return 常量 / 常量表达式）。"""
    if isinstance(stmt, ast.Pass):
        return True
    if isinstance(stmt, ast.Return):
        value = stmt.value
        return value is None or isinstance(value, ast.Constant)
    return isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant)


def _silent_handlers_without_comment(path: pathlib.Path) -> list[int]:
    """返回目标文件中「静默且无注释」的 ExceptHandler 行号清单。"""
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    comments = {tok.start[0] for tok in tokenize.generate_tokens(
        io.StringIO(src).readline) if tok.type == tokenize.COMMENT}
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler) or not node.body:
            continue
        if not all(_is_silent_stmt(stmt) for stmt in node.body):
            continue
        line_range = range(node.lineno, (node.end_lineno or node.lineno) + 1)
        if any(line in comments for line in line_range):
            continue
        offenders.append(node.lineno)
    return offenders


def test_no_uncommented_silent_except_handlers():
    """静默回退必须说明理由（F-5 守卫；违规清单即待补注释底账）。"""
    offenders = []
    for path in sorted(WUXING_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        for lineno in _silent_handlers_without_comment(path):
            offenders.append(f"{path.relative_to(WUXING_ROOT)}:{lineno}")
    assert not offenders, (
        "静默异常回退缺注释（请在下述 handler 块内注明理由，或改为降级日志）：\n"
        + "\n".join(offenders)
    )
