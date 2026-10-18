"""用户视角模拟（P10 核心）：真实工作流量化"重复 vs 变体"占比——R3 语义缓存拍板依据。

工作流场景：
  continuation —— 接续任务（run→改需求→resume）——重复为主（R1/R2 已覆盖）
  modification —— 修改任务（同任务微改 3 版）——变体（精确缓存 0 收益，R3 候选）
  regression   —— 回归验证（321 套件重跑）——确定为主（R2 覆盖）
输出：repeat_ratio / variant_ratio + R3 经济性 verdict（模拟语义缓存增益 vs 误命中风险）。
"""
import pathlib
import tempfile

from wuxing.engine import Engine


def _run_count(eng, task_text) -> int:
    """单次 run_task 的调用增量（缓存计数器是累积值——需快照差值）。"""
    rc_before = eng.reply_cache.misses
    sc_before = eng.shape_cache.misses
    eng.run_task(task_text)
    return (eng.reply_cache.misses - rc_before) + (eng.shape_cache.misses - sc_before)


def user_flow_simulate(n_variants: int = 3, n_continuations: int = 5) -> dict:
    base = "写一封请假邮件"
    variants = [f"写一篇请假邮件（{i}）" for i in range(1, n_variants + 1)]

    # 1. continuation 场景：run → 改需求 → resume（重复：同任务链）
    wd = pathlib.Path(tempfile.mkdtemp())
    e1 = Engine(workdir=wd)
    cont_calls = 0
    for _ in range(n_continuations):
        cont_calls += _run_count(e1, base)

    # 2. modification 场景：变体（精确缓存 miss——R3 候选）
    e2 = Engine(workdir=pathlib.Path(tempfile.mkdtemp()))
    variant_calls = 0
    for v in variants:
        variant_calls += _run_count(e2, v)

    # 3. regression 场景：321 套件
    import json
    e3 = Engine(workdir=pathlib.Path(tempfile.mkdtemp()))
    texts = []
    for fname in ["calibration_tasks", "mega_tasks", "domain_tasks", "professional_tasks"]:
        with open(f"golden_ratio/data/{fname}.json", encoding="utf-8") as f:
            data = json.load(f)
        texts += [t["task_text"] for t in data["tasks"]]
    with open("golden_ratio/data/github_tasks.json", encoding="utf-8") as f:
        gdata = json.load(f)
    texts += [t["task_text"] for t in gdata["tasks"]]
    reg_calls = 0
    for t in texts:
        reg_calls += _run_count(e3, t)

    total = cont_calls + variant_calls + reg_calls
    repeat_ratio = round((cont_calls + reg_calls) / max(1, total), 3)
    variant_ratio = round(variant_calls / max(1, total), 3)

    # R3 经济性 verdict：语义缓存只在 variant 场景有增益；误命中风险折减 30%
    r3_gain = round(variant_calls * 0.7, 1)  # 乐观假设：70% 变体可被相似命中
    verdict = (
        "R3 值得投入" if variant_ratio >= 0.3 and r3_gain > total * 0.2
        else "R3 暂缓" if variant_ratio < 0.15
        else "R3 观察（数据边缘，需真实使用数据）"
    )
    return {
        "repeat_ratio": repeat_ratio,
        "variant_ratio": variant_ratio,
        "call_breakdown": {"continuation": cont_calls, "variants": variant_calls,
                           "regression": reg_calls},
        "r3_simulated_gain": r3_gain,
        "r3_economic_verdict": verdict,
    }


if __name__ == "__main__":
    import json
    print(json.dumps(user_flow_simulate(), ensure_ascii=False, indent=2))
