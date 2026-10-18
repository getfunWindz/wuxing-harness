"""真实测试批跑器（P0-3 A · 评估行动项）：固定任务集 + 机械断言 + 结构化报告。

用法：
  python -m scripts.real_suite --list
  python -m scripts.real_suite --only greet-cli --yes          # 单任务（真实花费）
  python -m scripts.real_suite --kind cli --yes
  python -m scripts.real_suite --kind theroad --base-url http://127.0.0.60:8723 --yes

纪律：
  - 默认 dry-run（只列任务/断言，不执行）；--yes 才真实执行（消耗 API）。
  - 断言机械可判：状态 / 产物文件（存在且非空）/ pytest（声明的测试文件=任务验收门禁；
    全工作区跑为观察面——E0-2/A2，模型追加测试失败不回灌任务失败）/ 票据（all_done）。
  - 报告：<root>/out/report-<ts>.json + 控制台摘要（含成本与缓存占比）。
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
import time

from wuxing.verify_gold import agreement_summary, gold_agreement

REPO = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_SUITE = REPO / "eval" / "real" / "tasks.json"
DEFAULT_ROOT = REPO / "real_test" / "real_suite"


def load_suite(path) -> dict:
    data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    return {"version": str(data.get("version") or "v1"),
            "tasks": list(data.get("tasks") or [])}


def check_files(wd: pathlib.Path, files: list) -> dict:
    """文件断言：存在且非空。"""
    missing = []
    for f in files or []:
        p = pathlib.Path(wd) / str(f)
        if not p.exists() or p.stat().st_size <= 0:
            missing.append(str(f))
    return {"ok": not missing, "missing": missing}


def check_pytest(wd: pathlib.Path, targets: list | None = None,
                 timeout: int = 300) -> dict:
    """pytest 断言（E0-2/A2 口径）。

    targets=声明的测试文件（任务验收门禁——只跑声明面）；
    targets=None → 全工作区（legacy；含模型追加测试，供观察面使用）。
    """
    cmd = [sys.executable, "-m", "pytest", "-q",
           *[str(t) for t in (targets or [])]]
    r = subprocess.run(
        cmd, cwd=str(wd),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout, check=False,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    tail = (r.stdout or "").strip().splitlines()[-1:] or [""]
    return {"ok": r.returncode == 0, "tail": tail[0][:160]}


def _declared_tests(files: list) -> list:
    """声明测试文件筛选（E0-2/A2）：basename test_* 或 *_test.py（保序）。"""
    out: list = []
    for f in files or []:
        base = pathlib.PurePosixPath(str(f).replace("\\", "/")).name
        if base.startswith("test_") or base.endswith("_test.py"):
            out.append(str(f))
    return out


def check_tickets(tickets: list, expect: str) -> dict:
    """票据断言：all_done = 全部票据 done。"""
    statuses = {str(t.get("id")): str(t.get("status")) for t in tickets or []}
    if expect == "all_done":
        bad = {k: v for k, v in statuses.items() if v != "done"}
        return {"ok": not bad, "expect": expect, "statuses": statuses,
                "not_done": bad}
    return {"ok": True, "expect": expect, "statuses": statuses}


def summarize(rows: list) -> dict:
    """汇总：通过数/成本/耗时。"""
    total_cost = 0.0
    for r in rows:
        try:
            total_cost += float(r.get("cost") or 0.0)
        except (TypeError, ValueError):
            pass
    return {"tasks": len(rows),
            "passed": sum(1 for r in rows if r.get("ok")),
            "failed": [r.get("id") for r in rows if not r.get("ok")],
            "total_cost": round(total_cost, 4),
            "total_duration_s": round(sum(r.get("duration_s") or 0
                                          for r in rows), 1)}


def run_cli_task(t: dict, root: pathlib.Path) -> dict:
    """CLI 类：engine 进程内（new 工作区 + auto_confirm）→ 状态/文件/pytest 断言。

    注意：cfg=None（与 CLI 同源——三层配置合并含 ~/.wuxing/config.jsonc 的
    llm=deepseek:...）；显式传 EngineConfig() 会跳过文件配置 → 退化为 mock。
    """
    import shutil

    from wuxing.engine import Engine
    wd = pathlib.Path(root) / str(t["id"])
    shutil.rmtree(wd, ignore_errors=True)  # 每次运行全新工作区（防状态污染）
    wd.mkdir(parents=True, exist_ok=True)
    eng = Engine(workdir=wd, auto_confirm=True)
    t0 = time.time()
    res = eng.run_task(str(t["task"]))
    status = str(getattr(res, "status", ""))
    metrics = getattr(res, "metrics", None) or {}
    cost = metrics.get("cost") or {}
    row = {"id": t["id"], "kind": "cli", "workspace": str(wd),
           "status": status, "duration_s": round(time.time() - t0, 1),
           "cost": cost.get("estimate"),
           "cache_read_ratio": cost.get("cache_read_ratio"),
           "shape_notice": str(getattr(eng, "_shape_notice", "") or "")[:200],
           "checks": {}}
    expect = str(t.get("expect_status") or "done")
    row["checks"]["status"] = {"ok": status == expect, "expect": expect,
                               "actual": status}
    row["checks"]["files"] = check_files(wd, t.get("files") or [])
    if t.get("pytest"):
        # E0-2/A2：门禁=声明的测试文件；全工作区跑（含模型追加测试）仅作观察面
        declared = _declared_tests(t.get("files") or [])
        row["checks"]["pytest"] = check_pytest(wd, declared or None)
        if declared and row["checks"]["pytest"]["ok"]:
            row["pytest_full"] = check_pytest(wd)
    # C3：verify 金标校准（有声明才记——观测项，不介入 ok 门禁）
    gold = gold_agreement(t, getattr(res, "units", None), status=status)
    if gold is not None:
        row["verify_gold"] = gold
    row["ok"] = all(c.get("ok") for c in row["checks"].values())
    return row


# ---- theroad（REST）辅助 ----

def _req(base: str, method: str, path: str, body=None, timeout: int = 120):
    import urllib.error
    import urllib.request
    data = (json.dumps(body, ensure_ascii=False).encode("utf-8")
            if body is not None else None)
    req = urllib.request.Request(
        base + path, data=data, method=method,
        headers={"X-Wuxing": "1", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def _find_ws(base: str, path: str) -> str | None:
    st, d = _req(base, "GET", "/api/v1/workspaces", timeout=30)
    if st != 200:
        return None
    target = str(pathlib.Path(path).resolve()).lower()
    for w in d.get("workspaces") or []:
        try:
            if str(pathlib.Path(str(w.get("path"))).resolve()).lower() == target:
                return str(w.get("id"))
        except OSError:
            continue
    st, d = _req(base, "POST", "/api/v1/workspaces",
                 {"path": str(pathlib.Path(path).resolve())}, timeout=30)
    return str(d.get("id")) if st == 200 else None


def run_theroad_task(t: dict, root: pathlib.Path, base: str) -> dict:
    """票据类：重置失败票 → 提交 → 确认回路 → 票据断言（需运行中的壳服务）。"""
    wd = pathlib.Path(t["ws_path"])
    if not wd.is_absolute():
        wd = REPO / wd
    ws = _find_ws(base, str(wd))
    row = {"id": t["id"], "kind": "theroad", "workspace": str(wd),
           "status": "", "duration_s": 0.0, "cost": None,
           "cache_read_ratio": None, "checks": {}}
    if not ws:
        row["checks"]["workspace"] = {"ok": False, "error": "工作区不可达"}
        row["ok"] = False
        return row
    t0 = time.time()
    if t.get("reset_failed"):
        st, _d = _req(base, "POST",
                      f"/api/v1/workspaces/{ws}/tickets/reset", {}, timeout=30)
        row["checks"]["reset"] = {"ok": st == 200}
    if t.get("reset_ids"):
        st, _d = _req(base, "POST",
                      f"/api/v1/workspaces/{ws}/tickets/reset",
                      {"ids": [str(x) for x in t["reset_ids"]]}, timeout=30)
        row["checks"]["reset"] = {"ok": st == 200}
    session = str(t.get("session") or "")
    st, _d = _req(base, "POST", f"/api/v1/workspaces/{ws}/tasks",
                 {"text": str(t.get("submit_text") or "批跑回归"),
                  "session": session or None})
    row["checks"]["submit"] = {"ok": st in (200, 202)}
    for _ in range(1200):  # 等 run 结束
        time.sleep(1.5)
        _s, snap = _req(base, "GET", f"/api/v1/workspaces/{ws}/snapshot",
                        timeout=30)
        if not snap.get("active_run"):
            break
    confirms = 0
    for _ in range(200):  # 确认回路（含 409 busy 重试）
        _s, snap = _req(base, "GET", f"/api/v1/workspaces/{ws}/snapshot",
                        timeout=30)
        active = snap.get("active_run") or {}
        pending = (active.get("pending_confirms")
                   or snap.get("pending_confirms") or [])
        run = snap.get("run_id") or active.get("run_id") or ""
        if pending and run:
            items = [[p["unit_id"], True] for p in pending]
            st2, _d2 = _req(base, "POST",
                            f"/api/v1/workspaces/{ws}/tasks/{run}/confirm",
                            {"items": items, "reason": "批跑自动放行"})
            if st2 == 200:
                confirms += 1
            time.sleep(3)
            continue
        if not snap.get("active_run"):
            break
        time.sleep(3)
    _s, snap = _req(base, "GET", f"/api/v1/workspaces/{ws}/snapshot",
                    timeout=30)
    res = snap.get("result") or {}
    row["status"] = str(res.get("status") or "")
    row["duration_s"] = round(time.time() - t0, 1)
    row["confirms"] = confirms
    metrics = res.get("metrics") or {}
    cost = metrics.get("cost") or {}
    row["cost"] = cost.get("estimate")
    row["cache_read_ratio"] = cost.get("cache_read_ratio")
    expect = str(t.get("expect_status") or "done")
    row["checks"]["status"] = {"ok": row["status"] == expect,
                               "expect": expect, "actual": row["status"]}
    if t.get("expect_tickets"):
        _s, td = _req(base, "GET", f"/api/v1/workspaces/{ws}/tickets",
                      timeout=30)
        row["checks"]["tickets"] = check_tickets(td.get("tickets") or [],
                                                 str(t["expect_tickets"]))
    # C3：verify 金标校准（HTTP 路径无单元明细——回退到状态判定）
    gold = gold_agreement(t, None, status=row["status"])
    if gold is not None:
        row["verify_gold"] = gold
    row["ok"] = all(c.get("ok") for c in row["checks"].values())
    return row


def main() -> int:
    ap = argparse.ArgumentParser(prog="real-suite",
                                 description="真实测试批跑器（P0-3 A）")
    ap.add_argument("--suite", default=str(DEFAULT_SUITE))
    ap.add_argument("--root", default=str(DEFAULT_ROOT))
    ap.add_argument("--only", default="", help="仅跑指定 id（逗号分隔）")
    ap.add_argument("--kind", default="", choices=["", "cli", "theroad"])
    ap.add_argument("--base-url", default="http://127.0.0.60:8723")
    ap.add_argument("--yes", action="store_true", help="真实执行（默认 dry-run）")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    suite = load_suite(args.suite)
    tasks = suite["tasks"]
    if args.only:
        want = {x.strip() for x in args.only.split(",") if x.strip()}
        tasks = [t for t in tasks if str(t.get("id")) in want]
    if args.kind:
        tasks = [t for t in tasks if str(t.get("kind")) == args.kind]
    if args.list or not args.yes:
        print(f"[real-suite] {args.suite} · {len(tasks)} 任务（dry-run）")
        for t in tasks:
            checks = []
            if t.get("expect_status"):
                checks.append("status=" + str(t["expect_status"]))
            if t.get("files"):
                checks.append("files=" + ",".join(t["files"]))
            if t.get("pytest"):
                checks.append("pytest")
            if t.get("expect_tickets"):
                checks.append("tickets=" + str(t["expect_tickets"]))
            if t.get("verify_gold"):
                checks.append("gold=" + str(t["verify_gold"].get("expect")))
            print(f"  - {t['id']} [{t.get('kind')}] {'/'.join(checks)}")
        if not args.yes:
            print("[real-suite] 加 --yes 真实执行（消耗 API 费用）")
        return 0

    root = pathlib.Path(args.root)
    (root / "out").mkdir(parents=True, exist_ok=True)
    rows = []
    for t in tasks:
        print(f"[real-suite] 执行 {t['id']} …", flush=True)
        if str(t.get("kind")) == "theroad":
            row = run_theroad_task(t, root, args.base_url)
        else:
            row = run_cli_task(t, root)
        rows.append(row)
        mark = "PASS" if row.get("ok") else "FAIL"
        print(f"  [{mark}] {t['id']} status={row.get('status')} "
              f"cost={row.get('cost')} checks={row.get('checks')}")
    summary = summarize(rows)
    gold_summary = agreement_summary([r.get("verify_gold") for r in rows])
    ts = int(time.time())
    out = root / "out" / f"report-{ts}.json"
    out.write_text(json.dumps({"suite": args.suite, "summary": summary,
                               "verify_gold": gold_summary,
                               "rows": rows}, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(f"[real-suite] 汇总：{summary['passed']}/{summary['tasks']} 通过 · "
          f"成本 {summary['total_cost']} 元 · {summary['total_duration_s']}s")
    if gold_summary["decided"] > 0:
        print(f"[real-suite] verify 金标：{gold_summary['agreed']}/"
              f"{gold_summary['decided']} 一致（率 {gold_summary['rate']:.2f}；"
              f"不可判 {gold_summary['undecided']}）")
    else:
        print("[real-suite] verify 金标：本次无金标样本")
    print(f"[real-suite] 报告：{out}")
    return 0 if not summary["failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
