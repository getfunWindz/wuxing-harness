#!/usr/bin/env python3
"""壳 E2E 全量 runner：本地与 CI 同口径（一条命令）。

用法：
  python e2e/shell/run_all.py [--only NAME ...] [--list]

- 夹具套件（10）：每套件前夹具零态重启（8833）；wayfinder 为
  create → restore 重启 → verify 三阶段；
- 自管理套件（2）：ui_fixes（8834）/ robust（8835）自行 spawn/kill 服务；
- 日志：e2e/shell/.runtime/artifacts/<ts>/<suite>.log
- 退出码：全过 0；任一失败 1；前置缺失（Edge/前端部署件）2。
"""
import argparse
import datetime
import os
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PORT = 8833
EDGE_DEFAULT = "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"

# (套件名, 步骤列表)；步骤 = "restart" | "restart restore" | "node <脚本> [参数…]"
SUITES = [
    ("wayfinder", ["restart",
                   "node wayfinder_check.js --phase=create",
                   "restart restore",
                   "node wayfinder_check.js --phase=verify"]),
    ("design_card", ["restart", "node check_design_card.js"]),
    ("modes", ["restart", "node modes_check.js"]),
    ("next_slice", ["restart", "node check_next_slice.js"]),
    ("context", ["restart", "node context_check.js"]),
    ("e2_ui", ["restart", "node e2_ui_check.js"]),
    ("g8_m3", ["restart", "node g8_m3_check.js"]),
    ("u5", ["restart", "node u5_remaining_check.js"]),
    ("g1", ["restart", "node g1_branch_check.js"]),
    ("ui_fixes", ["node ui_fixes_check.js"]),     # 自管理 8834
    ("robust", ["node check_slice_robust.js"]),   # 自管理 8835
    ("settings_layout", ["restart", "node settings_layout_check.js"]),  # 2026-10-01：设置 provider 行不塌缩
    ("switching", ["restart", "node switching_check.js"]),  # Wave-2 T5：切换回归（Bug#1-4）
    ("artifact_preview", ["restart", "node artifact_preview_check.js"]),  # A6（W1）：产物预览/动作
    ("ask_flow", ["restart", "node check_ask.js"]),  # E2-5（A10）：提问挂起/答复
    ("worktree", ["restart", "node check_worktree.js"]),  # E3-1/R5（T5）：隔离运行 Review/Apply
    ("confirm_view", ["restart", "node check_confirm_view.js"]),  # 重大优化清单 #2：四要素渲染/折叠/回退/T-2 通知/T-4 键盘
    ("a11y", ["restart", "node check_a11y.js"]),          # T-3：无障碍基线（键盘链/弹层语义/名称/对比度）
    ("failure_class", ["restart", "node check_failure_class.js"]),  # S1-C：失败分类呈现/自动重试痕迹
    ("mobile", ["restart", "node mobile_check.js"]),  # O5 T4-A：移动视口适配
]


def prune_batches(art_root, keep: int = 20) -> int:
    """E3-5（CU10）：批次产物保留最近 `keep` 批（最旧删除）——返回删除数。

    失败静默（本地资产纪律；清理不是生命线）。
    """
    try:
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from wuxing.cleanup import prune_dirs
        return int(prune_dirs(art_root, "*", keep).get("removed", 0))
    except Exception:
        # 清理失败不阻断 E2E 结果（护城河不是生命线）
        return 0


def _edge_path() -> str:
    return os.environ.get("EDGE_PATH") or EDGE_DEFAULT


def _env(needs_fixture: bool, out_dir: pathlib.Path) -> dict:
    env = {**os.environ,
           "OUT_DIR": str(out_dir),
           "PYTHON": sys.executable}
    if needs_fixture:
        env["SHELL_URL"] = f"http://127.0.0.60:{PORT}/next/"
    return env


def _run(cmd: list, log_fh, env: dict) -> int:
    log_fh.write("$ " + " ".join(str(c) for c in cmd) + "\n")
    log_fh.flush()
    proc = subprocess.run(cmd, cwd=HERE, env=env, check=False,
                          stdout=log_fh, stderr=subprocess.STDOUT)
    return proc.returncode


def _run_suite(name: str, steps: list, art: pathlib.Path,
               suffix: str = "") -> int:
    """跑一套件（返回 0=全过）；日志写 art/<name><suffix>.log。"""
    needs_fixture = steps[0].startswith("restart")
    log = art / f"{name}{suffix}.log"
    code = 0
    with open(log, "a", encoding="utf-8") as fh:
        for step in steps:
            if step.startswith("restart"):
                cmd = [sys.executable, str(HERE / "restart_fixture.py")]
                if step.endswith("restore"):
                    cmd.append("restore")
            else:
                parts = step.split()
                cmd = ["node", str(HERE / parts[1])] + parts[2:]
            code = _run(cmd, fh, _env(needs_fixture, art))
            if code != 0:
                break
    return code


def main() -> int:
    ap = argparse.ArgumentParser(description="壳 E2E 全量 runner")
    ap.add_argument("--only", nargs="*", default=None,
                    help="只跑指定套件（名称前缀匹配）")
    ap.add_argument("--retry-failed", type=int, default=0,
                    help="失败套件重跑次数（CI 慢环境用；默认 0=严格）")
    ap.add_argument("--list", action="store_true", help="列出套件")
    args = ap.parse_args()

    if args.list:
        for name, _steps in SUITES:
            print(name)
        return 0

    edge = _edge_path()
    if not pathlib.Path(edge).is_file():
        print(f"前置缺失：浏览器未找到（{edge}）——设置 EDGE_PATH 或安装 Edge", file=sys.stderr)
        return 2
    static = ROOT / "wuxing" / "shell" / "web" / "static" / "next"
    if not static.is_dir():
        print("前置缺失：前端未部署——先运行 `cd apps/shell && npm run deploy`", file=sys.stderr)
        return 2

    picked = [s for s in SUITES
              if not args.only or any(s[0].startswith(o) for o in args.only)]
    if not picked:
        print("没有匹配的套件（--list 查看清单）", file=sys.stderr)
        return 2

    # 产物目录命名用本机时间戳（展示用途；非时间语义计算）——保持本地时区
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")  # noqa: DTZ005
    art = HERE / ".runtime" / "artifacts" / ts
    art.mkdir(parents=True, exist_ok=True)

    failed: list[str] = []
    retried_pass: list[str] = []
    for name, steps in picked:
        print(f"— {name} …", end=" ", flush=True)
        code = _run_suite(name, steps, art)
        print("PASS" if code == 0 else "FAIL")
        if code != 0:
            failed.append(name)

    suite_steps = dict(picked)
    for attempt in range(1, max(0, int(args.retry_failed)) + 1):
        if not failed:
            break
        still: list[str] = []
        for name in failed:
            print(f"— retry{attempt} {name} …", end=" ", flush=True)
            code = _run_suite(name, suite_steps[name], art,
                              suffix=f"-retry{attempt}")
            print("PASS" if code == 0 else "FAIL")
            if code == 0:
                retried_pass.append(name)
            else:
                still.append(name)
        failed = still

    print(f"\n结果：{len(picked) - len(failed)}/{len(picked)} 套件通过"
          f"（日志：{art}）")
    if retried_pass:
        print("重试通过（首次失败）：" + ", ".join(retried_pass))
    # E3-5（CU10）：批次保留最近 20（最旧删除）——本地资产纪律
    _pruned = prune_batches(art.parent, keep=20)
    if _pruned:
        print(f"清理：删除旧批次 {_pruned} 个（保留最近 20）")
    if failed:
        print("失败：" + ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
