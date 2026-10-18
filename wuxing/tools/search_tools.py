"""搜索工具（Wave-1 Task B1/B2）：grep/glob——优先 ripgrep，缺失时纯 Python 兜底。

设计（用户裁决 2026-10-01 · 壳体验对照调研）：
  - rg 优先（`WUXING_RIPGREP` 显式路径 > PATH）；rg 缺失 → 纯 Python 扫描
    （无 rg 环境不得失效；探针用于决定描述文案）；
  - 只读工具（read 权限）；跳 VCS/缓存目录（.git/.wuxing/node_modules 等）；
  - 默认前 N 条 + 超限提示；单行截断；不越工作区（Workspace._safe_path 守卫）。
"""
import fnmatch
import json
import os
import pathlib
import re
import shutil
import subprocess

from wuxing.protocols import Tool, ToolResult

_SKIP_DIRS = {".git", ".svn", ".hg", ".bzr", ".wuxing", "node_modules",
              "__pycache__", ".pytest_cache", "dist", "build"}
_MAX_FILE_BYTES = 1_000_000
_MAX_LINE_CHARS = 2000


def find_ripgrep() -> str | None:
    """ripgrep 探测：WUXING_RIPGREP 显式路径优先，其次 PATH。"""
    env = os.environ.get("WUXING_RIPGREP", "").strip()
    if env and pathlib.Path(env).is_file():
        return env
    return shutil.which("rg")


class GrepTool(Tool):
    """按正则搜索工作区文件内容（path:line: 预览；只读）。"""

    def __init__(self, ws, max_matches: int = 100):
        self._ws = ws
        self._max = max(1, int(max_matches))

    def name(self):
        return "grep"

    def description(self):
        mode = "ripgrep" if find_ripgrep() else "内置扫描"
        return ("在工作区内按正则搜索文件内容（结果 path:line: 预览；默认前 "
                f"{self._max} 条，单行截断 {_MAX_LINE_CHARS} 字符；{mode}）。"
                "支持 include 过滤（如 *.py）与目录/文件 path；不改文件。")

    def input_schema(self):
        return {"type": "object", "properties": {
            "pattern": {"type": "string"},
            "path": {"type": "string"},
            "include": {"type": "string"},
            "max_results": {"type": "integer"},
            "case_insensitive": {"type": "boolean"}}, "required": ["pattern"]}

    def permission(self):
        return {"read": True, "write": False, "execute": False,
                "network": False, "destructive": False}

    def execute(self, pattern="", path=".", include="", max_results=0,
                case_insensitive=False, **kw):
        pattern = str(pattern or "")
        if not pattern.strip():
            return ToolResult(status="error", tool_name=self.name(),
                              error="empty pattern")
        try:
            flags = re.IGNORECASE if case_insensitive else 0
            re.compile(pattern, flags)
        except re.error as exc:
            return ToolResult(status="error", tool_name=self.name(),
                              error=f"invalid pattern: {exc}")
        try:
            root = self._ws._safe_path(path or ".")
        except ValueError:
            return ToolResult(status="blocked", tool_name=self.name(),
                              error=f"not found (outside workspace): {path}")
        limit = int(max_results or 0) or self._max
        rg = find_ripgrep()
        try:
            if rg:
                hits, more = self._grep_rg(rg, root, pattern, include, limit,
                                           case_insensitive)
            else:
                hits, more = self._grep_py(root, pattern, include, limit,
                                           case_insensitive)
        except (OSError, subprocess.SubprocessError) as exc:
            return ToolResult(status="error", tool_name=self.name(),
                              error=str(exc))
        if not hits:
            return ToolResult(status="ok", tool_name=self.name(),
                              content="No matches found")
        body = "\n".join(hits)
        if more:
            body += (f"\n\n[{limit} matches limit reached; more matches may "
                     f"exist——use max_results={limit * 2} for more, "
                     f"or refine pattern]")
        return ToolResult(status="ok", tool_name=self.name(), content=body)

    # ---- ripgrep 路径 ----
    def _grep_rg(self, rg, root, pattern, include, limit, ci):
        args = [rg, "--json", "--line-number", "--color=never", "--hidden",
                "--glob", "!.git", "--glob", "!.wuxing", "--no-config"]
        if include:
            args += ["--glob", include]
        if ci:
            args.append("--ignore-case")
        args += ["--", pattern, str(root)]
        proc = subprocess.run(args, capture_output=True, timeout=30,
                              check=False)
        hits, more = [], False
        for line in (proc.stdout or b"").decode("utf-8", "replace").splitlines():
            if not line.strip():
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("type") != "match":
                continue
            if len(hits) >= limit:
                more = True
                break
            d = ev.get("data", {})
            p = str(d.get("path", {}).get("text", ""))
            try:
                rel = str(pathlib.Path(p).resolve().relative_to(
                    pathlib.Path(self._ws.root).resolve())).replace("\\", "/")
            except ValueError:
                rel = pathlib.Path(p).name
            ln = int(d.get("line_number", 0) or 0)
            text = ""
            lines_blob = d.get("lines", {}).get("text", "")
            if lines_blob:
                text = str(lines_blob).splitlines()[0]
            hits.append(f"{rel}:{ln}: {text[:_MAX_LINE_CHARS]}")
        return hits, more

    # ---- Python 兜底（无 rg；跳 VCS/缓存目录与二进制大文件）----
    def _grep_py(self, root, pattern, include, limit, ci):
        flags = re.IGNORECASE if ci else 0
        rx = re.compile(pattern, flags)
        root_p = pathlib.Path(self._ws.root)
        if not root.exists():
            return [], False
        if root.is_file():
            files = [root]
        else:
            files = []
            skip_norm = {os.path.normcase(d) for d in _SKIP_DIRS}
            for dp, dirs, names in os.walk(root):
                dirs[:] = [d for d in dirs
                           if os.path.normcase(d) not in skip_norm]
                for name in names:
                    files.append(pathlib.Path(dp) / name)
        hits, more = [], False
        for fp in sorted(files):
            try:
                if fp.stat().st_size > _MAX_FILE_BYTES:
                    continue
                raw = fp.read_bytes()
            except OSError:
                continue
            if b"\x00" in raw[:4096]:
                continue
            try:
                rel = str(fp.resolve().relative_to(
                    root_p.resolve())).replace("\\", "/")
            except ValueError:
                continue
            if include and not (fnmatch.fnmatch(fp.name, include)
                                or fnmatch.fnmatch(rel, include)):
                continue
            for i, line in enumerate(
                    raw.decode("utf-8", "replace").splitlines(), 1):
                if rx.search(line):
                    if len(hits) >= limit:
                        return hits, True
                    hits.append(f"{rel}:{i}: {line[:_MAX_LINE_CHARS]}")
        return hits, more


class GlobTool(Tool):
    """按 glob 模式列出工作区文件（仅文件——目录不出；只读）。"""

    def __init__(self, ws, max_results: int = 100):
        self._ws = ws
        self._max = max(1, int(max_results))

    def name(self):
        return "glob"

    def description(self):
        mode = "ripgrep" if find_ripgrep() else "内置扫描"
        return ("按 glob 模式列出工作区内文件路径（只出文件；默认前 "
                f"{self._max} 条；{mode}）。示例：**/*.py、src/*.md；不改文件。")

    def input_schema(self):
        return {"type": "object", "properties": {
            "pattern": {"type": "string"},
            "path": {"type": "string"},
            "max_results": {"type": "integer"}}, "required": ["pattern"]}

    def permission(self):
        return {"read": True, "write": False, "execute": False,
                "network": False, "destructive": False}

    def execute(self, pattern="", path=".", max_results=0, **kw):
        pattern = str(pattern or "").strip()
        if not pattern:
            return ToolResult(status="error", tool_name=self.name(),
                              error="empty pattern")
        try:
            root = self._ws._safe_path(path or ".")
        except ValueError:
            return ToolResult(status="blocked", tool_name=self.name(),
                              error=f"not found (outside workspace): {path}")
        limit = int(max_results or 0) or self._max
        rg = find_ripgrep()
        try:
            if rg:
                files, more = self._glob_rg(rg, root, pattern, limit)
            else:
                files, more = self._glob_py(root, pattern, limit)
        except (OSError, subprocess.SubprocessError) as exc:
            return ToolResult(status="error", tool_name=self.name(),
                              error=str(exc))
        if not files:
            return ToolResult(status="ok", tool_name=self.name(),
                              content="No files found")
        body = "\n".join(files)
        if more:
            body += (f"\n\n[{limit} files limit reached; more files may "
                     f"exist——use max_results={limit * 2} for more, "
                     f"or refine pattern]")
        return ToolResult(status="ok", tool_name=self.name(), content=body)

    # ---- ripgrep 路径（cwd=root；输出相对 root → 转相对工作区）----
    def _glob_rg(self, rg, root, pattern, limit):
        args = [rg, "--files", "--color=never", "--hidden",
                "--glob", "!.git", "--glob", "!.wuxing",
                "--glob", pattern, "--no-config"]
        proc = subprocess.run(args, capture_output=True, timeout=30,
                              cwd=str(root), check=False)
        root_p = pathlib.Path(self._ws.root).resolve()
        files, more = [], False
        for line in (proc.stdout or b"").decode("utf-8", "replace").splitlines():
            p = line.strip()
            if not p:
                continue
            if len(files) >= limit:
                more = True
                break
            try:
                rel = str((root / p).resolve().relative_to(
                    root_p)).replace("\\", "/")
            except ValueError:
                rel = p.replace("\\", "/")
            files.append(rel)
        return files, more

    # ---- Python 兜底（无 rg）----
    def _glob_py(self, root, pattern, limit):
        root_p = pathlib.Path(self._ws.root).resolve()
        if not root.exists():
            return [], False
        walk_root = root if root.is_dir() else root.parent
        skip_norm = {os.path.normcase(d) for d in _SKIP_DIRS}
        files, more = [], False
        for dp, dirs, names in os.walk(walk_root):
            dirs[:] = [d for d in dirs if os.path.normcase(d) not in skip_norm]
            for name in names:
                fp = pathlib.Path(dp) / name
                if not fp.is_file():
                    continue
                try:
                    rel = str(fp.resolve().relative_to(
                        root_p)).replace("\\", "/")
                except ValueError:
                    continue
                if not (fnmatch.fnmatch(name, pattern)
                        or fnmatch.fnmatch(rel, pattern)):
                    continue
                if len(files) >= limit:
                    return files, True
                files.append(rel)
        return files, more
