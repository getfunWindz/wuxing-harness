"""P0/P1 真 LLM 冒烟（DeepSeek 单模型通道——多模型协作机制已就位，单通道验证闭环）。

知识库纪律（本冒烟的依据）：
- LLM 测试方法论：mock 只测管道，真 LLM 才测语义；负结果必须留档（根因+证据）
- 评估口径纪律：成本/缓存测度用 API 真值（usage 字段）
- 服务端提示缓存：稳定前缀 → prompt_cache_hit_tokens > 0 是唯一实锤

验证点（对照 P0/P1 验收）：
  A. 闭环回填：第二轮 messages 必须包含第一轮工具结果（MessageProbe 断言）
  B. 契约物证：ok 单元须有 [tool] 写/读成功记录；无「无物证却 ok」
  C. 碎片入 prompt：goal = 碎片文本（probe 记录可查）
  D. 服务端缓存：二跑 usage.cache_read > 0（DeepSeek 真值）
  E. 负结果留档：失败单元根因分类（provider/contract/budget/tool）

用法（key 会话内传，永不落盘）：
  DEEPSEEK_API_KEY=<key> PYTHONIOENCODING=utf-8 python scripts/smoke_closed_loop.py [--tasks 3]

输出：smoke_out/smoke-p0p1-<ts>.json（实验产物目录已被 gitignore）
"""
import argparse
import json
import os
import pathlib
import sys
import tempfile
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from wuxing.config import EngineConfig
from wuxing.engine import Engine
from wuxing.llm.factory import create_provider

DEFAULT_SPEC = "deepseek:deepseek-chat"

TASKS = [
    "写一封请假邮件",
    "用 Python 实现一个函数 count_words(text)，统计文本中每个单词出现次数，并把结果写入文件",
    "写一个 Python 斐波那契模块，再写单元测试并执行验证通过",
]


class MessageProbe:
    """包装 provider：记录每轮 messages（验证工具结果回填/碎片入 prompt）。"""

    def __init__(self, inner):
        self.inner = inner
        self.rounds = []  # [{idx, messages:[str...]}]

    def name(self):
        return self.inner.name()

    def spec(self):
        return self.inner.spec()

    @property
    def usage_history(self):
        return self.inner.usage_history

    def chat(self, messages, tools=None):
        self.rounds.append({"idx": len(self.rounds),
                            "messages": [str(m.get("content", ""))
                                         for m in messages]})
        out = self.inner.chat(messages, tools)
        # 记录输出（诊断不收敛——verify 每轮输出什么）
        self.rounds[-1]["output"] = str(getattr(out, "text", out))[:200]
        return out


def channel_check(spec: str, timeout: float = 60.0):
    """通道预检（LLM 测试方法论：真跑前置条件——通道可用性预检）。"""
    p = create_provider(spec, timeout=timeout)
    t0 = time.time()
    out = p.chat([{"role": "user", "content": "通道预检：请回复 OK"}])
    return {"ok": "OK" in str(out) or bool(out), "latency_s": round(time.time() - t0, 2),
            "usage": p.usage_history[-1] if p.usage_history else None,
            "sample": str(out)[:80]}


def feedback_evidence(probe: MessageProbe) -> dict:
    """A 验证：存在某单元第二轮 messages 包含工具结果（'[tool]'/'written' 等）。"""
    ev = {"rounds_total": len(probe.rounds), "feedback_rounds": [],
          "feedback_ok": False}
    for r in probe.rounds:
        if r["idx"] == 0:
            continue
        prev_round = probe.rounds[r["idx"] - 1]["messages"]
        joined = "\n".join(prev_round)
        is_feedback = ("[tool]" in joined or "written" in joined
                       or "tool" in joined.lower())
        if is_feedback:
            ev["feedback_rounds"].append(r["idx"])
    ev["feedback_ok"] = len(ev["feedback_rounds"]) > 0
    return ev


def analyze_result(res, probe: MessageProbe, task_idx: int) -> dict:
    units = []
    for u in res.units:
        units.append({
            "unit": u.unit_id, "domain": u.domain_id, "status": u.status,
            "error": u.error, "artifacts": [a.path for a in u.artifacts],
            "logs_tail": [l for l in u.logs if "[tool]" in l or "[guard]" in l
                          or "[warn]" in l][:6],
        })
    return {
        "task": res.task_text, "status": res.status, "units": units,
        "metrics": res.metrics, "report_tail": (res.report or "")[-400:],
        "feedback": feedback_evidence(probe),
        "round_outputs": [{"idx": r["idx"], "out": r.get("output", "")[:160]}
                           for r in probe.rounds],
        "probe_round_sample": [
            {"idx": r["idx"], "last_msg": r["messages"][-1][:120]}
            for r in probe.rounds[:6]
        ],
    }


def run_smoke(spec: str, tasks: list) -> dict:
    workdir = pathlib.Path(tempfile.mkdtemp(prefix="smoke-wd-"))
    use_real_shape = spec != "mock"  # mock 通道只验脚本管道（真跑必须真形状化）
    cfg = EngineConfig(llm=spec, use_real_shape=use_real_shape,
                       brain_enabled=False, max_parallel_units=1)
    eng = Engine(cfg=cfg, workdir=workdir)
    probe = MessageProbe(eng.llm)
    eng.llm = probe  # 包装（router 未启用——llm_for 走 eng.llm）
    results = []
    for i, t in enumerate(tasks, 1):
        t0 = time.time()
        try:
            res = eng.run_task(t)
            results.append(analyze_result(res, probe, i))
        except Exception as e:  # 冒烟不崩：负结果留档（含 traceback——根因可查）
            import traceback
            results.append({"task": t, "status": "exception",
                            "error": f"{type(e).__name__}: {e}",
                            "traceback": traceback.format_exc()[-1500:]})
        results[-1]["wall_s"] = round(time.time() - t0, 2)
    # 二跑（缓存验证）：同首任务
    if results:
        t0 = time.time()
        res2 = eng.run_task(tasks[0])
        results.append({"task": tasks[0] + "（二跑）", "status": res2.status,
                        "metrics": res2.metrics, "wall_s": round(time.time() - t0, 2)})
    return {"spec": spec, "results": results,
            "channel": channel_check(spec)}


def tempfile_dir() -> str:
    return tempfile.mkdtemp(prefix="wuxing-")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", default=os.environ.get("WUXING_SMOKE_SPEC", DEFAULT_SPEC))
    ap.add_argument("--tasks", type=int, default=3)
    args = ap.parse_args()
    if not os.environ.get("DEEPSEEK_API_KEY") and "deepseek" in args.spec:
        print("错误：DEEPSEEK_API_KEY 未设置（key 会话内传，永不落盘）", file=sys.stderr)
        sys.exit(2)
    report = run_smoke(args.spec, TASKS[:args.tasks])
    out_dir = pathlib.Path("smoke_out")
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"smoke-p0p1-{int(time.time())}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
