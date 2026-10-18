"""精确测试 CLI（B 阶段；原称准测试）：隐藏 rubric + 单轮大对话 + 机械体检 + judge B。

用法：
  python -m scripts.accuracy_runner --task acc-001 --llm deepseek:deepseek-flash \
      --judge deepseek:deepseek-v4-pro --real-shape --workdir real_test/acc-001
  python -m scripts.accuracy_runner --task acc-001 --mech-only \
      --workdir real_test/acc-001-smoke
"""
import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from wuxing.accuracy import gather_pipeline, load_tasks, write_report


def _find_task(tasks: list, key: str):
    for t in tasks:
        if t["id"] == key or t["id"] == f"acc-{key}":
            return t
    return None


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="accuracy-runner",
        description="精确测试（B，原称准测试）：隐藏 rubric + 单轮大对话 + 机械体检 + B/C 评审")
    ap.add_argument("--task", required=True, help="任务 id（acc-001 / 001）")
    ap.add_argument("--tasks-dir", default="eval/accuracy_tasks")
    ap.add_argument("--workdir", default=None,
                    help="隔离工作区（默认 real_test/<task-id>）")
    ap.add_argument("--llm", default="mock",
                    help="受测 provider spec（mock/deepseek:...）")
    ap.add_argument("--judge", default="deepseek:deepseek-v4-pro",
                    help="judge provider spec（独立模型——盲评）")
    ap.add_argument("--real-shape", action="store_true", help="真形状化（需 key）")
    ap.add_argument("--max-parallel", type=int, default=None)
    ap.add_argument("--mech-only", action="store_true", help="仅机械体检（不跑 judge）")
    ap.add_argument("--report", default=None,
                    help="报告路径（默认 <workdir>/accuracy_report.md）")
    args = ap.parse_args()

    tasks = load_tasks(args.tasks_dir)
    task = _find_task(tasks, args.task)
    if task is None:
        print(f"[accuracy] 未找到任务：{args.task}"
              f"（可用：{[t['id'] for t in tasks]}）")
        return 2
    wd = pathlib.Path(args.workdir) if args.workdir \
        else pathlib.Path("real_test") / task["id"]
    llm = None if args.llm == "mock" else args.llm
    judge_provider = None
    if not args.mech_only:
        from wuxing.llm.factory import create_provider
        judge_provider = create_provider(args.judge)
    print(f"[accuracy] task={task['id']} workdir={wd} llm={args.llm} "
          f"judge={'(off)' if args.mech_only else args.judge}")
    result = gather_pipeline(task, wd, llm=llm, real_shape=args.real_shape,
                             judge_provider=judge_provider,
                             max_parallel=args.max_parallel)
    v = result.get("verdict")
    print(f"[accuracy] 运行：{result['run']['status']}"
          f"（{result['run']['duration_s']}s）· 文件 {result['checkup']['total_files']}"
          f" · B 分 {'—' if v is None else v['total']}")
    rep = pathlib.Path(args.report) if args.report \
        else (wd / "accuracy_report.md")
    p = write_report(rep, result)
    print(f"[accuracy] 报告：{p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
