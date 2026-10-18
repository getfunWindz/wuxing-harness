"""SEC2 扩展审查 CLI（设计 §3.3）。

用法：python -m scripts.check_extension <entry-point|package|path> [--static] [--json]

退出码：0=未发现 danger 级标注；1=发现 danger；2=用法/加载错误。
注意：动态模式（默认）会执行扩展代码——只审查可信来源；静态仅扫源码，覆盖有限。
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from wuxing import ext_audit


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="WUXING 扩展分发审查")
    ap.add_argument("target", help="entry-point 名 / 已安装包名 / 本地路径")
    ap.add_argument("--static", action="store_true",
                    help="仅静态扫描（不执行扩展代码；覆盖有限）")
    ap.add_argument("--json", action="store_true", help="JSON 输出")
    args = ap.parse_args(argv)
    try:
        audit = ext_audit.inspect_extension(args.target, static=args.static)
    except Exception as e:  # 加载/注册失败如实可见
        print(f"加载失败：{type(e).__name__}: {e}", file=sys.stderr)
        return 2
    flags = ext_audit.risk_flags(audit)
    if args.json:
        print(json.dumps({"audit": dataclasses.asdict(audit),
                          "flags": [dataclasses.asdict(f) for f in flags]},
                         ensure_ascii=False, indent=2))
    else:
        print(ext_audit.render_report(audit))
    return 1 if any(f.severity == "danger" for f in flags) else 0


if __name__ == "__main__":
    sys.exit(main())
