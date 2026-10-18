"""仓库推送卫生检查（用户裁决 2026-09-30）——推送前复检入口。

用法：python -m scripts.repo_hygiene [--root DIR]

失败项（推送前必须为 0）：
  1. 污物路径模式：日志/缓存/临时/编辑器/环境/构建产物（含 e2e 运行时目录）
  2. 未跟踪且未忽略文件
  3. 关键本地区域仍被 .gitignore 覆盖（real_test/·smoke_out/·e2e 运行时……）
  4. 高置信密钥模式（sk-/ghp_/github_pat_/AKIA/PRIVATE KEY）
  5. 超大跟踪文件（> 1 MiB）
告警项（不阻断）：
  6. 机器路径残留（C:/Users/ 等——历史文档惯例可保留）
退出码：0 通过；1 有违规。
"""
from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys

if hasattr(sys.stdout, "reconfigure"):  # Windows 控制台编码防御（UTF-8 输出）
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

JUNK_DIR_RE = re.compile(
    r"(^|/)(__pycache__|\.pytest_cache|\.ruff_cache|\.mypy_cache|node_modules"
    r"|\.idea|\.vscode|dist|egg-info)(/|$)")
JUNK_EXT_RE = re.compile(r"\.(log|tmp|pyc|pyo|bak|orig|rej|swp|swo)$", re.IGNORECASE)
JUNK_NAME_RE = re.compile(r"(^|/)(\.DS_Store|Thumbs\.db)$")
JUNK_ENV_RE = re.compile(r"(^|/)\.env($|\.)")
E2E_RUNTIME_RE = re.compile(
    r"^e2e/shell/(fake-ws|fake-ws2|fake-ws-keep|g8-claim-ws|g8-par-ws"
    r"|next-tmp-ws|picked-ws-[^/]+|\.runtime|visual|node_modules|__pycache__)(/|$)")

ENV_ALLOW = {".env.example", ".env.sample", ".env.template"}

SECRET_RES = (
    ("openai-style key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("github token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("github pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("aws access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
)

MACHINE_RE = re.compile(r"C:/Users/|C:\\Users\\")

LARGE_LIMIT = 1024 * 1024  # 1 MiB

REQUIRED_IGNORED = (
    "real_test",
    "smoke_out",
    ".superpowers",
    "apps/shell/node_modules",
    "apps/shell/web/dist",
    "apps/shell/desktop/dist",
    "wuxing/shell/web/static/next",
    "wuxing_harness.egg-info",
    "e2e/shell/node_modules",
    "e2e/shell/fake-ws",
    "e2e/shell/fake-ws2",
    "e2e/shell/fake-ws-keep",
    "e2e/shell/g8-claim-ws",
    "e2e/shell/g8-par-ws",
    "e2e/shell/next-tmp-ws",
    "e2e/shell/.runtime",
    "e2e/shell/visual",
)


def find_junk_tracked(paths: list[str]) -> list[str]:
    """污物模式（可跟踪清单内不应出现的路径）。"""
    out = []
    for p in paths:
        if (JUNK_DIR_RE.search(p) or JUNK_EXT_RE.search(p)
                or JUNK_NAME_RE.search(p) or E2E_RUNTIME_RE.search(p)
                or (JUNK_ENV_RE.search(p)
                    and pathlib.PurePosixPath(p).name not in ENV_ALLOW)):
            out.append(p)
    return out


def find_secrets(files: dict[str, str]) -> list[tuple[str, str, str]]:
    """高置信密钥模式：[(path, 规则名, 摘录)]；低置信（短 token/演示值）不报。"""
    hits = []
    for path, text in files.items():
        for name, rx in SECRET_RES:
            m = rx.search(text)
            if m:
                snippet = text[max(0, m.start() - 20):m.start() + 40].strip()
                hits.append((path, name, snippet))
    return hits


def find_large_tracked(items: list[tuple[str, int]],
                       limit: int = LARGE_LIMIT) -> list[str]:
    return [p for p, size in items if size > limit]


def find_machine_paths(files: dict[str, str]) -> list[str]:
    return [p for p, text in files.items() if MACHINE_RE.search(text)]


def _git(root: pathlib.Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=str(root), check=False,
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    return proc.stdout


def _tracked(root: pathlib.Path) -> list[str]:
    return [p for p in _git(root, "ls-files", "-z").split("\0") if p]


def _read_text_files(root: pathlib.Path, paths: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for rel in paths:
        path = root / rel
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if b"\0" in data[:8192]:          # 二进制跳过
            continue
        out[rel] = data.decode("utf-8", errors="replace")
    return out


def _is_ignored(root: pathlib.Path, rel: str) -> bool:
    proc = subprocess.run(["git", "check-ignore", "-q", rel],
                          cwd=str(root), capture_output=True, check=False)
    return proc.returncode == 0


def run_checks(root: pathlib.Path) -> dict:
    tracked = _tracked(root)
    files = _read_text_files(root, tracked)
    sizes = []
    for rel in tracked:
        try:
            sizes.append((rel, (root / rel).stat().st_size))
        except OSError:
            pass
    untracked = [ln for ln in
                 _git(root, "status", "--porcelain",
                      "--untracked-files=all").splitlines()
                 if ln.startswith("??")]
    ignored_gaps = [rel for rel in REQUIRED_IGNORED
                    if (root / rel).exists() and not _is_ignored(root, rel)]

    junk = find_junk_tracked(tracked)
    secrets = find_secrets(files)
    large = find_large_tracked(sizes)
    machine = find_machine_paths(files)

    failures: list[tuple[str, list[str]]] = []
    if junk:
        failures.append(("污物模式", junk))
    if untracked:
        failures.append(("未跟踪且未忽略", untracked))
    if ignored_gaps:
        failures.append(("忽略覆盖缺口", ignored_gaps))
    if secrets:
        failures.append(("密钥模式", [f"{p}:{n}" for p, n, _ in secrets]))
    if large:
        failures.append(("超大文件（>1MiB）", large))
    return {
        "tracked": len(tracked),
        "failures": failures,
        "warnings": ([("机器路径残留（历史文档可保留）", machine)]
                     if machine else []),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="仓库推送卫生检查")
    ap.add_argument("--root", default=".")
    args = ap.parse_args(argv)
    root = pathlib.Path(args.root).resolve()

    report = run_checks(root)
    print(f"repo-hygiene: {report['tracked']} 个跟踪文件 · root={root}")
    for name, items in report["failures"]:
        print(f"[FAIL] {name}：{len(items)}")
        for it in items[:10]:
            print(f"       - {it}")
        if len(items) > 10:
            print(f"       … 其余 {len(items) - 10} 条")
    for name, items in report["warnings"]:
        print(f"[WARN] {name}：{len(items)} 个文件")
        for it in items[:5]:
            print(f"       - {it}")
    if report["failures"]:
        print(f"结果：FAIL（{len(report['failures'])} 类违规）")
        return 1
    print(f"结果：PASS（0 违规；告警 {len(report['warnings'])} 类）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
