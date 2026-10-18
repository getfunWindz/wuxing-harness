"""本地 CI 门禁（与 .github/workflows/ci.yml 同口径）——串行，任一失败即非零退出。

用法：python -m scripts.ci_check
提交前可选执行；远端 CI（GitHub Actions）为同一命令集。
Node 侧门禁（apps/shell）：node_modules 存在时执行 `npm run check`，否则跳过提示。
"""
import pathlib
import shutil
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

CHECKS = [
    ("引擎测试", [sys.executable, "-m", "pytest", "wuxing/tests/", "-q"]),
    ("算法层回归", [sys.executable, "-m", "pytest", "golden_ratio/tests/", "-q"]),
    ("静态检查", [sys.executable, "-m", "ruff", "check",
                  "wuxing", "golden_ratio", "scripts", "e2e",
                  "--ignore", "BLE001,S110,B017"]),
    ("协议对拍", [sys.executable, "-m", "scripts.gen_protocol_ts", "--check"]),
    ("工作流校验", [sys.executable, "-m", "scripts.workflow_check"]),
]


def main() -> int:
    failed = []
    for name, cmd in CHECKS:
        print(f"[ci] {name} ...", flush=True)
        result = subprocess.run(cmd, check=False)
        if result.returncode != 0:
            failed.append(name)

    shell_dir = REPO_ROOT / "apps" / "shell"
    npm = shutil.which("npm")
    if npm and (shell_dir / "node_modules").is_dir():
        print("[ci] 前端门禁（apps/shell）...", flush=True)
        result = subprocess.run([npm, "run", "check"], cwd=shell_dir,
                                check=False)
        if result.returncode != 0:
            failed.append("前端门禁")
    else:
        print("[ci] 跳过前端门禁（apps/shell/node_modules 未安装）")

    if failed:
        print(f"[ci] 失败：{failed}")
        return 1
    print("[ci] 全部通过（引擎 + 算法 + ruff + 协议 + 前端）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
