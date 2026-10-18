"""代码审查辅助：AST 静态扫描（死代码 + 重复 + 结构）。"""
import ast
import collections
import pathlib

# 已核对意向接口（2026-10-03 用户口径：为用户自定义预留/框架回调/评测工具面）——
# 扫描候选时跳过；新增须注来源与理由（勿把死代码混入）。
_REVIEWED_INTENTIONAL = {
    "aclose",              # McpConnectionPool 异步清理 API（close/aclose 成对——文档声明）
    "descendants",         # Provenance 子链查询（血缘/审查工具面——delegate git 参考）
    "for_unit",            # TraceLogger 按单元过滤（评测回放视图——L1-1 设计）
    "gen_schema",          # 配置 JSON Schema 生成（IDE 体验——工具面）
    "is_run_terminal",     # state_machine 谓词（P0-4 状态词汇 API 面）
    "log_message",         # http.server 框架回调（有意空实现——静默）
    "save_tasks",          # task_miner 公开 API（采集→落盘四件套）
}


def _iter_py(root: pathlib.Path):
    """root 下所有 .py（含 tests；__pycache__ 除外）——引用面用。"""
    for f in root.rglob("*.py"):
        if "__pycache__" not in str(f).replace("\\", "/"):
            yield f


def _collect_refs(ref_files) -> collections.Counter:
    """引用计数：名称/属性/字符串字面量（按名引用——getattr/注册表/回调）。"""
    refs = collections.Counter()
    for f in ref_files:
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        # 不可读/不可解析文件跳过（扫描器韧性设计：继续处理其余文件）
        except Exception:  # noqa: S112
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                refs[node.attr] += 1
            elif isinstance(node, ast.Name):
                refs[node.id] += 1
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    refs[alias.name] += 1   # 导入即引用（含 as 别名——原名计）
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                refs[node.value] += 1   # 按名引用（getattr/注册表/回调）
    return refs


def scan_dead_code(root: pathlib.Path, *, extra_whitelist=(),
                   max_refs: int = 0, ref_roots=()):
    """死代码候选（引用数 ≤ max_refs，默认 0）——Q4 降噪。

    降噪（四因素评审 §1.3 P2——回调/公开 API 误报）：
      - dunder 名（协议方法——由运行时/运算符调用）排除；
      - 模块 ``__all__`` 声明的名字（公开 API）排除；
      - 字符串字面量出现的名字视为引用（getattr/注册表/回调按名调用）；
      - ``extra_whitelist`` 显式导出/回调清单（集合）；
      - ``ref_roots`` 额外引用源（D2/E0-5/P3-8）：scripts//e2e/ 或仓库根等
        ——只贡献引用计数、不产生候选；root 内 tests/ 同样只作引用源
        （模块限定调用与测试引用不再误报）。
    口径：引用数 > max_refs 即不候选（原 ≤1 口径把「单次引用」也计入
    误报——单次引用是真实使用）。
    """
    producers = collections.defaultdict(list)
    exported = {str(n) for n in (extra_whitelist or ())}
    root = pathlib.Path(root)
    # 引用面：root（含 tests）+ ref_roots（文件/目录）——集合去重
    ref_files: set = {f.resolve() for f in _iter_py(root)}
    for r in (ref_roots or ()):
        rp = pathlib.Path(r)
        if rp.is_dir():
            ref_files.update(f.resolve() for f in _iter_py(rp))
        elif rp.is_file() and rp.suffix == ".py":
            ref_files.add(rp.resolve())
    refs = _collect_refs(sorted(ref_files))
    # 生产面：root 非测试文件——收集定义 + __all__
    for f in root.rglob("*.py"):
        fp = str(f).replace("\\", "/")
        if "__pycache__" in fp or "/tests/" in fp:
            continue
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        # 不可读/不可解析文件跳过（扫描器韧性设计：继续处理其余文件）
        except Exception:  # noqa: S112
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
                producers[node.name].append(f.name)
            if isinstance(node, ast.Assign):
                for tgt in node.targets:
                    if isinstance(tgt, ast.Name) and tgt.id == "__all__":
                        for elt in getattr(node.value, "elts", ()):
                            if isinstance(elt, ast.Constant) \
                                    and isinstance(elt.value, str):
                                exported.add(elt.value)
    candidates = []
    for name, files in producers.items():
        if name.startswith("__") and name.endswith("__"):
            continue                    # 协议方法（运行时调用）
        if name in exported:
            continue                    # __all__/显式白名单
        if refs.get(name, 0) <= max_refs:
            candidates.append((name, files, refs.get(name, 0)))
    return candidates

def scan_duplicate_lines(root: pathlib.Path):
    """重复行检测（>3 文件相同行——简单启发式）。"""
    line_owner = collections.defaultdict(list)
    for f in root.rglob("*.py"):
        fp = str(f).replace("\\", "/")
        if "__pycache__" in fp or "/tests/" in fp:
            continue
        try:
            for line in f.read_text(encoding="utf-8").splitlines():
                s = line.strip()
                if len(s) > 30 and not s.startswith(("#", "\"\"\"", "import ")):
                    line_owner[s].append(f.name)
        # 不可读文件跳过（扫描器韧性设计：继续处理其余文件）
        except Exception:  # noqa: S112
            continue
    return [(l, owners) for l, owners in line_owner.items() if len(owners) > 3]

if __name__ == "__main__":
    root = pathlib.Path("wuxing")
    repo = pathlib.Path(__file__).resolve().parents[1]
    # D2（E0-5/P3-8）：scripts//e2e/ 为 root 外引用源（模块限定调用）；
    # root 内 tests/ 由引用面自动纳入（只作引用源，不产生候选）
    dead = scan_dead_code(root, extra_whitelist=_REVIEWED_INTENTIONAL,
                          ref_roots=[repo / "scripts", repo / "e2e"])
    print(f"=== 死代码候选（引用数=0，Q4 降噪后）{len(dead)} 条 ===")
    for name, files, cnt in dead[:30]:
        print(f"  {name} | 定义于 {files} | 引用 {cnt}")
    dup = scan_duplicate_lines(root)
    print(f"\n=== 重复行（>3 文件）==={len(dup)} 条")
    for line, owners in dup[:10]:
        print(f"  {line[:60]!r} | {owners[:4]}")
