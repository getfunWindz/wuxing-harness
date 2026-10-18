"""G4 最小运行时 SDK 示例（设计 `docs/WUXING_最小运行时SDK_G4_设计_2026-09-26.md`）。

用法（仓库根目录）：
    python docs/examples/sdk_run.py                          # mock（零凭据，默认可跑）
    python docs/examples/sdk_run.py --workdir ./sdk-demo     # 显式工作目录
    # 真实模型：凭据走环境变量（隔离态不读 ~/.wuxing/credentials.json）
    DEEPSEEK_API_KEY=sk-... python docs/examples/sdk_run.py \
        --llm deepseek:deepseek-v4-flash

要点：
- 显式装配：不读文件配置 / 用户级技能 / 扩展 / 凭据存储；
- 工具 = 核心五件；技能/扩展/MCP/FSC/智脑全关；
- 落盘只发生在 workdir（未给 → 临时目录，末尾打印）。
"""
import argparse

from wuxing.sdk import build_runtime


def main() -> int:
    ap = argparse.ArgumentParser(description="WUXING 最小运行时 SDK 示例")
    ap.add_argument("--task", default="写一篇请假邮件", help="任务文本")
    ap.add_argument("--llm", default=None,
                    help="模型 spec（如 deepseek:deepseek-v4-flash）；缺省 mock")
    ap.add_argument("--workdir", default=None,
                    help="工作目录（缺省临时目录）")
    args = ap.parse_args()

    rt = build_runtime(llm=args.llm, workdir=args.workdir)
    res = rt.run(args.task)

    print(f"状态：{res.status}")
    print(f"工作区：{res.workspace}")
    print(f"产物：{len(res.artifacts)} 个")
    for a in res.artifacts:
        print(f"  - {a}")
    print("-" * 40)
    print(res.report)
    return 0 if res.status == "done" else 1


if __name__ == "__main__":
    raise SystemExit(main())
