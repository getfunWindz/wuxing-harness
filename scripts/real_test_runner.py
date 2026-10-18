"""真实测试 CLI（薄壳——核心逻辑在 wuxing.real_test）。

用法：
  python -m scripts.real_test_runner --profile novice --workdir ./rt/novice-1
  python -m scripts.real_test_runner --profile novice \
      --llm deepseek:deepseek-v4-flash --real-shape --workdir ./rt/novice-1
  python -m scripts.real_test_runner --list
"""
import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from wuxing.real_test import PROFILES, run_profile


def main():
    ap = argparse.ArgumentParser(
        prog="real-test-runner",
        description="真实测试：模拟真实用户多轮使用（画像剧本→会话式 harness→"
                    "双口径缓存命中率报告）")
    ap.add_argument("--profile", default="novice", choices=sorted(PROFILES),
                    help="用户画像（novice/expert/precise）")
    ap.add_argument("--workdir", default=None,
                    help="隔离工作区（默认 ./real_test/<profile>-<时间戳>）")
    ap.add_argument("--llm", default="mock",
                    help="provider spec（mock/deepseek:... 等）")
    ap.add_argument("--real-shape", action="store_true", help="真形状化（需 key）")
    ap.add_argument("--max-turns", type=int, default=None, help="限制轮数（调试）")
    ap.add_argument("--parallel", type=int, default=None,
                    help="碎片并行度（S3 实验——默认配置 2）")
    ap.add_argument("--fsc", action="store_true",
                    help="启用 FSC 碎片会话延续（跨轮工作流键匹配复用）")
    ap.add_argument("--list", action="store_true", help="列出画像与剧本")
    args = ap.parse_args()

    if args.list:
        for name, p in sorted(PROFILES.items()):
            print(f"{name}（{p['name']}）：{len(p['turns'])} 轮")
            for i, t in enumerate(p["turns"], 1):
                label = t.get("text", "[自动注入]") if t["kind"] == "static" \
                    else "[自动注入]"
                print(f"  {i}. {label[:60]}")
        return

    wd = pathlib.Path(args.workdir) if args.workdir else (
        pathlib.Path("real_test") / f"{args.profile}-{int(__import__('time').time())}")
    wd.mkdir(parents=True, exist_ok=True)
    llm = None if args.llm == "mock" else args.llm
    print(f"[real-test] profile={args.profile} workdir={wd} llm={args.llm}")
    rows = run_profile(args.profile, workdir=wd, llm=llm,
                       real_shape=args.real_shape, max_turns=args.max_turns,
                       max_parallel=args.parallel, fsc=args.fsc)
    print(f"[real-test] 完成：{len(rows)} 轮——报告 {wd}/real_test_report.csv")


if __name__ == "__main__":
    main()
