#!/usr/bin/env python3
"""find-skill 查询客户端（SkillRadar Discover——URL 与 WUXING 配置 skill_radar_url 一致）。"""
import argparse
import json
import sys

DEFAULT_BASE = "https://api.skillradar.quest"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--goal", required=True)
    ap.add_argument("--constraints", default="")
    ap.add_argument("--keywords", default="")
    ap.add_argument("--max-results", type=int, default=5)
    ap.add_argument("--base-url", default=DEFAULT_BASE)
    args = ap.parse_args()
    from urllib.request import Request, urlopen
    payload = {"task_goal": args.goal, "task_constraints": args.constraints,
               "keywords": args.keywords, "max_results": args.max_results}
    req = Request(args.base_url.rstrip("/") + "/discover",
                  data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                  headers={"Content-Type": "application/json",
                           "User-Agent": "wuxing-find-skill/0.1"}, method="POST")
    try:
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(json.dumps({"error": f"{type(e).__name__}: {e}"}, ensure_ascii=False),
              file=sys.stderr)
        sys.exit(1)
    print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
