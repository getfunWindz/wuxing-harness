"""多模型配置自检（A5 前置）：对国内四模型通道调用 /models 核实 key 与模型 ID。

用法（env 未设置的通道跳过，不报错——key 一律环境变量、不落盘）：
  GLM_API_KEY=... MOONSHOT_API_KEY=... MIMO_API_KEY=... \
      python -m scripts.check_providers

配置口径（2026-09-12 官方文档核实）：
  deepseek-flash  → https://api.deepseek.com            （OpenAI 兼容；DEEPSEEK_API_KEY）
  glm-5.3-flash   → https://open.bigmodel.cn/api/paas/v4（OpenAI 兼容；GLM_API_KEY）
  kimi-k2.7-code  → https://api.moonshot.cn/v1          （OpenAI 兼容；MOONSHOT_API_KEY）
  mimo-v2.5       → https://api.xiaomimimo.com/v1       （OpenAI 兼容；MIMO_API_KEY）
"""
import json
import os
import urllib.request

CHANNELS = [
    ("deepseek-flash", "https://api.deepseek.com", "DEEPSEEK_API_KEY"),
    ("glm-5.3-flash", "https://open.bigmodel.cn/api/paas/v4", "GLM_API_KEY"),
    ("kimi-k2.7-code", "https://api.moonshot.cn/v1", "MOONSHOT_API_KEY"),
    ("mimo-v2.5", "https://api.xiaomimimo.com/v1", "MIMO_API_KEY"),
]


def main() -> int:
    checked = 0
    for name, base, env in CHANNELS:
        key = os.environ.get(env, "")
        if not key:
            print(f"[skip] {name}: 未设置 {env}")
            continue
        req = urllib.request.Request(
            base.rstrip("/") + "/models",
            headers={"Authorization": f"Bearer {key}"})
        try:
            data = json.loads(urllib.request.urlopen(req, timeout=30).read())
            ids = [m.get("id") for m in (data.get("data") or [])]
            checked += 1
            hit = "目标模型存在" if name in ids else "目标 ID 未见于列表"
            print(f"[ok] {name}: {hit} | 可用: {ids[:12]}")
        except Exception as e:
            print(f"[fail] {name}: {type(e).__name__}: {str(e)[:140]}")
    if checked == 0:
        print("[check] 未设置任何 key——key 会话内传或环境变量（不落盘）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
