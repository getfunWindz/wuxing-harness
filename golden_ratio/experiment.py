"""Q11 三臂对比实验框架：A 机械基线 / B 静态完整 / C 自适应（成功率记忆微调）。

指标：覆盖度 / 依赖完整率（底线）+ 粒度偏差（质量）+ 成本（llm_calls + 0.5×碎片数）。
C 臂：按 (主领域×难度) 分桶记忆切割成功率，成功率低于下限向 0 微调偏置、
高于上限回弹半步，参数钳制在 ±0.5；warm-up 集学习、test 集评估（防泄漏）。
"""
import copy
import random

from golden_ratio.calibrate import build_dag
from golden_ratio.config import AlgorithmConfig
from golden_ratio.difficulty import compute_shape
from golden_ratio.keyify import extract_keys
from golden_ratio.models import DAG
from golden_ratio.rebalance import rebalance
from golden_ratio.segment import segment


def granularity_deviation(actual, expected):
    """粒度偏差 = |实际碎片数 - 期望碎片数| / 期望碎片数。"""
    return abs(actual - expected) / expected if expected else 0.0


def cost_metric(llm_calls, cross_edges, coord_weight=0.5):
    """执行成本 = LLM 调用次数 + 协调权重 × 跨碎片依赖边数（每条边 = 一次跨碎片交接）。

    比"碎片数"更本质：碎片多但无依赖可并行执行，成本不高；碎片间依赖才产生协调成本。
    """
    return llm_calls + coord_weight * cross_edges


def effort_cv(efforts):
    """碎片工时变异系数（对照实验发现 2：gd 块数盲区的补充指标）。

    CV = std/mean，0 = 完全均匀，>0.5 = 严重失衡（大块+小块混杂）。
    单碎片或全同值 → 0。
    """
    if len(efforts) <= 1:
        return 0.0
    mean = sum(efforts) / len(efforts)
    if mean == 0:
        return 0.0
    var = sum((e - mean) ** 2 for e in efforts) / len(efforts)
    return min(1.0, (var ** 0.5) / mean)


def compliance_levels(effort, cfg):
    """〔deprecated v5.3〕三级合规判定：hard [4,120] / standard [8,80] / violation（§5 门禁）——_metrics 已内联，测试参照。"""
    h_lo, h_hi = cfg.hard_effort_interval
    s_lo, s_hi = cfg.effort_interval
    if s_lo <= effort <= s_hi:
        return "standard"
    if h_lo <= effort <= h_hi:
        return "hard"
    return "violation"


def arm_config(arm, cfg, cap=40.0):
    """三臂配置：A 关参数合成+关分层；B 校准参数；C 基于 B 运行时微调。

    cap：M 级上限（B 基线；C 方案按评估口径传 80 实现 cap 双标尺）。
    """
    c = copy.deepcopy(cfg)
    if arm == "A":
        c.alpha = c.beta = c.gamma = 0.0
        c.hierarchical_enabled = False
    if arm == "B":
        c.m_level_cap = cap                   # v4.1 B 基线收紧：M 级绝对上限（乘法收紧曾致小任务过碎，已修正）
        c.effort_ceiling = 1.15               # B微调v5.2定案：cap 软目标（软上限 46h，钳制不破 80）
    return c


def ema_update(stats, status, decay=0.9):
    """指数衰减更新：全部计数 × decay，当前状态 +1（旧信号指数遗忘）。"""
    return {k: round(v * decay + (1.0 if k == status else 0.0), 4)
            for k, v in stats.items()}


def hybrid_direction(global_stats, bucket_stats, seen, scale=5.0):
    """8.2.2 融合式方向：dir = w×桶 + (1−w)×全局，w = min(1, seen/scale)。

    连续过渡无突变：桶样本越多权重越大；冷桶（seen→0）退化为纯全局（即 8.2.1）。
    """
    w = min(1.0, seen / scale)
    return {k: round((1.0 - w) * global_stats.get(k, 0.0) + w * bucket_stats.get(k, 0.0), 4)
            for k in ("ok", "over", "under")}


class SuccessMemory:
    """〔deprecated v5.3〕(领域 × 难度) 分桶成功率记忆——旧 C 臂 v0 机制，仅供测试/历史参照。"""

    def __init__(self):
        self._buckets = {}

    def update(self, domain, difficulty, success):
        key = (domain, difficulty)
        hits, total = self._buckets.get(key, (0, 0))
        self._buckets[key] = (hits + (1 if success else 0), total + 1)

    def rate(self, domain, difficulty):
        hits, total = self._buckets.get((domain, difficulty), (0, 0))
        return hits / total if total else None


def adapt_bias(bias, rate, step=0.05, lo=-0.5, hi=0.5,
               low_target=0.6, high_target=0.9):
    """〔deprecated v5.3〕旧 C 臂微调规则（率 < 下限向 0 收；率 > 上限回弹半步；
    钳制 [lo, hi]）——被 BucketAdaptiveRunner 方向统计取代，仅测试参照。"""
    if rate is None:
        return bias
    if rate < low_target:
        if bias > 0:
            bias -= step
        elif bias < 0:
            bias += step
    elif rate > high_target:
        bias += step / 2 if bias >= 0 else -step / 2
    return max(lo, min(hi, round(bias, 4)))


def _run_task(dag, cfg, llm, task_text=""):
    """确定性 DAG → 完整流水线（绕过 LLM 模板匹配，样例集 dag_spec 即形状化输出）。"""
    before = llm.call_count
    shape = compute_shape(dag, cfg)
    frags = segment(dag, shape, llm, cfg, task_text=task_text)
    if not shape.fast_path:
        frags, _ = rebalance(frags, dag, cfg, shape)
    node_text = {n.id: n.text for n in dag.nodes}
    for f in frags:
        f.text = " ".join(node_text[nid] for nid in f.node_ids)
        f.key_tokens = extract_keys(f.text, cfg)
    return shape, frags, llm.call_count - before


def _metrics(tasks, llm, cfg):
    """在任务集上执行并汇总：覆盖度 / 依赖完整率 / 平均粒度偏差 / 平均成本 + 每任务粒度偏差。"""
    coverage = dep_ok = 0.0
    gd_sum = cost_sum = comp_sum = std_sum = cv_sum = 0.0
    per_gd = []
    n = len(tasks)
    for t in tasks:
        dag = build_dag(t["dag_spec"])
        shape, frags, calls = _run_task(dag, cfg, llm)
        flat = [nid for f in frags for nid in f.node_ids]
        if sorted(flat) == sorted(n.id for n in dag.nodes):
            coverage += 1.0
        if DAG.is_acyclic(dag):
            dep_ok += 1.0
        gd = granularity_deviation(len(frags), t["expected_fragments"])
        per_gd.append(gd)
        gd_sum += gd
        # 工时合规率：碎片工时落在 [8,80] 的比例（8/80 标准期望）
        from golden_ratio.effort import fragment_effort
        efforts = [fragment_effort(f, dag.nodes, shape, cfg) for f in frags]
        if len(efforts) <= 1:
            hard_ok = std_ok = 1.0              # 单碎片 = 原子任务豁免
        else:
            hard_ok = sum(1 for e in efforts
                          if cfg.hard_effort_interval[0] <= e <= cfg.hard_effort_interval[1])
            hard_ok /= len(efforts)
            std_ok = sum(1 for e in efforts
                         if cfg.effort_interval[0] <= e <= cfg.effort_interval[1])
            std_ok /= len(efforts)
        comp_sum += hard_ok
        std_sum += std_ok
        cv_sum += effort_cv(efforts)
        # 跨碎片依赖边数：边 (a,b) 两端在不同碎片 → 一次跨碎片协调
        node2frag = {nid: f.fragment_id for f in frags for nid in f.node_ids}
        cross_edges = sum(1 for a, b in dag.edges
                          if node2frag.get(a) and node2frag.get(b)
                          and node2frag[a] != node2frag[b])
        cost_sum += cost_metric(calls, cross_edges, cfg.exp_coord_weight)
    return {
        "coverage": round(coverage / n, 4),
        "dependency_integrity": round(dep_ok / n, 4),
        "avg_granularity_deviation": round(gd_sum / n, 4),
        "avg_cost": round(cost_sum / n, 4),
        "avg_effort_compliance": round(comp_sum / n, 4),
        "avg_standard_compliance": round(std_sum / n, 4),
        "avg_effort_cv": round(cv_sum / n, 4),
        "n_tasks": n,
        "per_task_gd": per_gd,
    }


class AdaptiveRunner:
    """〔deprecated v5.3〕C 臂 v1（探索数据确定）：全局单桶方向多数制——v4.1 起被
    BucketAdaptiveRunner 取代，仅测试/历史参照——统计过碎/过粗方向，
    多数方向驱动全局 merge_drop_ratio 微调（钳制 [0.5, 0.9]）；warm-up 学习、test 评估。

    探索结论（2026-08）：按 (领域×难度) 分桶在 24 任务上桶样本不足（0~2 条）导致微调无效果；
    全局单桶 + step=0.03 在 5 次重复下带来 ~6% 粒度改善，step≥0.2 过调劣化。
    """

    def __init__(self, cfg):
        self.cfg = copy.deepcopy(cfg)
        self.stats = {"ok": 0, "over": 0, "under": 0}
        self.adaptations = 0

    def run_warmup(self, tasks, llm):
        for t in tasks:
            dag = build_dag(t["dag_spec"])
            shape, frags, _ = _run_task(dag, self.cfg, llm)
            gd = granularity_deviation(len(frags), t["expected_fragments"])
            status = ("ok" if gd <= self.cfg.exp_success_threshold
                      else "over" if len(frags) > t["expected_fragments"]
                      else "under")
            # v3.4：EMA 衰减记忆（用户确认方案）——旧信号指数遗忘，近期方向主导
            self.stats = ema_update(self.stats, status, decay=self.cfg.exp_ema_decay)
            # v3.2：ceiling 微调步长按任务规模自适应（小任务 0.01 防过调，mega 0.05 有效）
            c_step = (self.cfg.exp_ceiling_step_mega
                      if shape.total_effort >= self.cfg.exp_mega_threshold
                      else self.cfg.exp_ceiling_step)
            # 冷启动保护：样本不足时不微调（防过调，τ² 测试发现 warm-up 0.65 过调劣化）
            # 方向多数制：累计方向驱动微调（每任务后更新）
            # over（过碎）→ 降低骤降阈值（更易合并）+ 放宽工时上限（允许更大块）
            # under（过粗）→ 反向收紧
            total_seen = sum(self.stats.values())
            if total_seen < self.cfg.exp_min_adapt_samples:
                continue
            if self.stats["over"] > self.stats["under"]:
                nr = max(0.5, self.cfg.merge_drop_ratio - self.cfg.exp_adapt_step)
                nc = min(self.cfg.exp_ceiling_clamp, self.cfg.effort_ceiling + c_step)
                if nr != self.cfg.merge_drop_ratio:
                    self.cfg.merge_drop_ratio = nr
                    self.adaptations += 1
                if nc != self.cfg.effort_ceiling:
                    self.cfg.effort_ceiling = nc
                    self.adaptations += 1
            elif self.stats["under"] > self.stats["over"]:
                nr = min(0.9, self.cfg.merge_drop_ratio + self.cfg.exp_adapt_step)
                nc = max(0.5, self.cfg.effort_ceiling - c_step)
                if nr != self.cfg.merge_drop_ratio:
                    self.cfg.merge_drop_ratio = nr
                    self.adaptations += 1
                if nc != self.cfg.effort_ceiling:
                    self.cfg.effort_ceiling = nc
                    self.adaptations += 1

    def run_test(self, tasks, llm):
        return _metrics(tasks, llm, self.cfg)


class BucketAdaptiveRunner:
    """C 臂分桶化（v4.1）：(主领域 × 难度档) 分桶，每桶独立 EMA 方向统计与微调。

    - 桶 key = (主领域, difficulty)，由 compute_shape 确定（不依赖合并参数，无鸡生蛋）
    - 每桶：EMA 方向统计（decay） + seen 计数（冷启动）+ ratio/ceiling 参数
    - warmup：用桶参数执行任务 → 更新桶 EMA → 桶内微调
    - test：按任务桶参数运行
    - 动机：跨领域方向分裂套件上全局单桶错调（C 落后 B 19%，v4.0 报告遗留 #1）
    """

    def __init__(self, cfg):
        self.cfg = copy.deepcopy(cfg)
        self.buckets = {}
        self.adaptations = 0
        # v5 混合策略（8.2.1 回退式）：全局 EMA 方向统计 + seen 计数
        self.global_stats = {"ok": 0.0, "over": 0.0, "under": 0.0}
        self.global_seen = 0

    def bucket_for(self, shape):
        """结构 key（阶段1-T1c）：（难度档 × 规模层 × 熵层）——开放标签可算、桶数有界。"""
        size_band = sum(1 for b in self.cfg.bucket_size_bands if shape.total_effort >= b)
        entropy_band = sum(1 for b in self.cfg.bucket_entropy_bands if shape.entropy >= b)
        return (shape.difficulty, size_band, entropy_band)

    def _direction_stats(self, global_stats, bucket, seen):
        """方向来源决策：融合式（8.2.2）→ 加权；回退式（8.2.1）→ 桶达标才用桶否则全局。"""
        if self.cfg.exp_hybrid_mode:
            return hybrid_direction(global_stats, bucket, seen,
                                    scale=self.cfg.exp_hybrid_scale)
        return bucket if seen >= self.cfg.exp_min_adapt_samples else global_stats

    def _bucket(self, key):
        b = self.buckets.get(key)
        if b is None:
            b = {"ok": 0.0, "over": 0.0, "under": 0.0, "seen": 0,
                 "ratio": self.cfg.merge_drop_ratio,
                 "ceiling": self.cfg.effort_ceiling,
                 "cap": self.cfg.m_level_cap}
            self.buckets[key] = b
        return b

    def _run_with_bucket(self, dag, b, llm):
        cfg_run = copy.deepcopy(self.cfg)
        cfg_run.merge_drop_ratio = b["ratio"]
        cfg_run.effort_ceiling = b["ceiling"]
        cfg_run.m_level_cap = b["cap"]
        return _run_task(dag, cfg_run, llm)

    def run_warmup(self, tasks, llm):
        for t in tasks:
            dag = build_dag(t["dag_spec"])
            shape = compute_shape(dag, self.cfg)
            key = self.bucket_for(shape)
            b = self._bucket(key)
            b["seen"] += 1
            _, frags, _ = self._run_with_bucket(dag, b, llm)
            gd = granularity_deviation(len(frags), t["expected_fragments"])
            status = ("ok" if gd <= self.cfg.exp_success_threshold
                      else "over" if len(frags) > t["expected_fragments"]
                      else "under")
            for k in ("ok", "over", "under"):
                b[k] = b[k] * self.cfg.exp_ema_decay + (1.0 if k == status else 0.0)
            # v5：全局统计同步更新（EMA 语义与桶一致）
            self.global_stats = ema_update(self.global_stats, status,
                                           decay=self.cfg.exp_ema_decay)
            self.global_seen += 1
            if self.global_seen < self.cfg.exp_min_adapt_samples:
                continue
            # 8.2.1/8.2.2：方向来源决策（回退式 or 融合式；微调对象仍是桶参数）
            dir_stats = self._direction_stats(self.global_stats, b, b["seen"])
            c_step = (self.cfg.exp_ceiling_step_mega
                      if shape.total_effort >= self.cfg.exp_mega_threshold
                      else self.cfg.exp_ceiling_step)
            if dir_stats["over"] > dir_stats["under"]:
                nr = max(0.5, b["ratio"] - self.cfg.exp_adapt_step)
                nc = min(self.cfg.exp_ceiling_clamp, b["ceiling"] + c_step)
                ncap = min(48.0, b["cap"] + 2.0)          # over → 放宽 M 级上限
                if nr != b["ratio"]:
                    b["ratio"] = nr
                    self.adaptations += 1
                if nc != b["ceiling"]:
                    b["ceiling"] = nc
                    self.adaptations += 1
                if ncap != b["cap"]:
                    b["cap"] = ncap
                    self.adaptations += 1
            elif dir_stats["under"] > dir_stats["over"]:
                nr = min(0.9, b["ratio"] + self.cfg.exp_adapt_step)
                nc = max(0.5, b["ceiling"] - c_step)
                ncap = max(32.0, b["cap"] - 2.0)          # under → 收紧 M 级上限
                if nr != b["ratio"]:
                    b["ratio"] = nr
                    self.adaptations += 1
                if nc != b["ceiling"]:
                    b["ceiling"] = nc
                    self.adaptations += 1
                if ncap != b["cap"]:
                    b["cap"] = ncap
                    self.adaptations += 1

    def run_test(self, tasks, llm):
        """返回 _metrics 同构 dict（按任务桶参数执行后聚合）。"""
        coverage = dep_ok = 0.0
        gd_sum = cost_sum = comp_sum = std_sum = cv_sum = 0.0
        per_gd = []
        n = len(tasks)
        for t in tasks:
            dag = build_dag(t["dag_spec"])
            shape = compute_shape(dag, self.cfg)
            key = self.bucket_for(shape)
            b = self._bucket(key)
            _, frags, calls = self._run_with_bucket(dag, b, llm)
            flat = [nid for f in frags for nid in f.node_ids]
            if sorted(flat) == sorted(n.id for n in dag.nodes):
                coverage += 1.0
            if DAG.is_acyclic(dag):
                dep_ok += 1.0
            gd = granularity_deviation(len(frags), t["expected_fragments"])
            per_gd.append(gd)
            gd_sum += gd
            node2frag = {nid: f.fragment_id for f in frags for nid in f.node_ids}
            cross_edges = sum(1 for a, b2 in dag.edges
                              if node2frag.get(a) and node2frag.get(b2)
                              and node2frag[a] != node2frag[b2])
            cost_sum += cost_metric(calls, cross_edges, self.cfg.exp_coord_weight)
            from golden_ratio.effort import fragment_effort
            efforts = [fragment_effort(f, dag.nodes, shape, self.cfg) for f in frags]
            if len(efforts) <= 1:
                comp_sum += 1.0
                std_sum += 1.0
            else:
                comp_sum += sum(1 for e in efforts
                                if self.cfg.hard_effort_interval[0] <= e <= self.cfg.hard_effort_interval[1]) / len(efforts)
                std_sum += sum(1 for e in efforts
                               if self.cfg.effort_interval[0] <= e <= self.cfg.effort_interval[1]) / len(efforts)
            cv_sum += effort_cv(efforts)
        return {
            "coverage": round(coverage / n, 4),
            "dependency_integrity": round(dep_ok / n, 4),
            "avg_granularity_deviation": round(gd_sum / n, 4),
            "avg_cost": round(cost_sum / n, 4),
            "avg_effort_compliance": round(comp_sum / n, 4),
            "avg_standard_compliance": round(std_sum / n, 4),
            "avg_effort_cv": round(cv_sum / n, 4),
            "n_tasks": n,
            "per_task_gd": per_gd,
        }


def run_experiment(tasks, llm, cfg=None, repeats=None, warmup_ratio=None, seed=None,
                   b_cap=40.0):
    if cfg is None:
        cfg = AlgorithmConfig()
    repeats = repeats or cfg.exp_repeats
    warmup_ratio = warmup_ratio or cfg.exp_warmup_ratio

    arms_cfg = {"A": arm_config("A", cfg), "B": arm_config("B", cfg, cap=b_cap)}
    agg = {k: {"coverage": 0.0, "dependency_integrity": 0.0,
               "gd": 0.0, "cost": 0.0, "comp": 0.0, "std": 0.0, "cv": 0.0,
               "n": 0, "adaptations": 0, "per_gd": {}} for k in ("A", "B", "C")}

    for rep in range(repeats):
        rng = random.Random((seed or 0) + rep)
        shuffled = list(tasks)
        rng.shuffle(shuffled)
        n_warm = max(1, int(len(shuffled) * warmup_ratio))
        warmup, test = shuffled[:n_warm], shuffled[n_warm:]

        for arm in ("A", "B"):
            m = _metrics(test, llm, arms_cfg[arm])
            for k in ("coverage", "dependency_integrity"):
                agg[arm][k] += m[k]
            agg[arm]["gd"] += m["avg_granularity_deviation"]
            agg[arm]["cost"] += m["avg_cost"]
            agg[arm]["comp"] += m["avg_effort_compliance"]
            agg[arm]["std"] += m["avg_standard_compliance"]
            agg[arm]["cv"] += m["avg_effort_cv"]
            agg[arm]["n"] = m["n_tasks"]
            for t, gd in zip(test, m["per_task_gd"]):
                agg[arm]["per_gd"].setdefault(t["id"], []).append(gd)

        runner = BucketAdaptiveRunner(arms_cfg["B"])
        runner.run_warmup(warmup, llm)
        m = runner.run_test(test, llm)
        for k in ("coverage", "dependency_integrity"):
            agg["C"][k] += m[k]
        agg["C"]["gd"] += m["avg_granularity_deviation"]
        agg["C"]["cost"] += m["avg_cost"]
        agg["C"]["comp"] += m["avg_effort_compliance"]
        agg["C"]["std"] += m["avg_standard_compliance"]
        agg["C"]["cv"] += m["avg_effort_cv"]
        agg["C"]["n"] = m["n_tasks"]
        agg["C"]["adaptations"] += runner.adaptations
        for t, gd in zip(test, m["per_task_gd"]):
            agg["C"]["per_gd"].setdefault(t["id"], []).append(gd)

    arms = {}
    for k in ("A", "B", "C"):
        a = agg[k]
        arms[k] = {
            "coverage": round(a["coverage"] / repeats, 4),
            "dependency_integrity": round(a["dependency_integrity"] / repeats, 4),
            "avg_granularity_deviation": round(a["gd"] / repeats, 4),
            "avg_cost": round(a["cost"] / repeats, 4),
            "avg_effort_compliance": round(a["comp"] / repeats, 4),
            "avg_standard_compliance": round(a["std"] / repeats, 4),
            "avg_effort_cv": round(a["cv"] / repeats, 4),
            "n_tasks": a["n"],
            "avg_adaptations": round(a["adaptations"] / repeats, 2),
            "per_task_gd": {tid: round(sum(v) / len(v), 4)
                            for tid, v in a["per_gd"].items()},
        }

    # 逐任务对比：win = B 或 C 的 gd ≤ A 的 gd（同任务、同重复）
    task_ids = sorted(arms["A"]["per_task_gd"])
    win_b = sum(1 for tid in task_ids
                if arms["B"]["per_task_gd"][tid] <= arms["A"]["per_task_gd"][tid])
    win_c = sum(1 for tid in task_ids
                if arms["C"]["per_task_gd"][tid] <= arms["A"]["per_task_gd"][tid])
    arms["_win_rate"] = {
        "B_not_worse_than_A": round(win_b / len(task_ids), 4),
        "C_not_worse_than_A": round(win_c / len(task_ids), 4),
    }

    def delta(metric_a, metric_b):
        return round(metric_a - metric_b, 4)

    return {
        "arms": arms,
        "deltas": {
            "B_vs_A": {"granularity_deviation": delta(
                arms["B"]["avg_granularity_deviation"],
                arms["A"]["avg_granularity_deviation"]),
                "cost": delta(arms["B"]["avg_cost"], arms["A"]["avg_cost"])},
            "C_vs_A": {"granularity_deviation": delta(
                arms["C"]["avg_granularity_deviation"],
                arms["A"]["avg_granularity_deviation"]),
                "cost": delta(arms["C"]["avg_cost"], arms["A"]["avg_cost"])},
            "C_vs_B": {"granularity_deviation": delta(
                arms["C"]["avg_granularity_deviation"],
                arms["B"]["avg_granularity_deviation"]),
                "cost": delta(arms["C"]["avg_cost"], arms["B"]["avg_cost"])},
        },
        "params": {"repeats": repeats, "warmup_ratio": warmup_ratio,
                   "success_threshold": cfg.exp_success_threshold,
                   "low_target": cfg.exp_low_target,
                   "high_target": cfg.exp_high_target,
                   "adapt_step": cfg.exp_adapt_step,
                   "bias_clamp": cfg.exp_bias_clamp},
    }


if __name__ == "__main__":
    import json
    import pathlib
    import sys
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
    from golden_ratio.calibrate import load_tasks
    from golden_ratio.llm import MockLLM
    report = run_experiment(load_tasks(), MockLLM(), AlgorithmConfig())
    print(json.dumps(report, ensure_ascii=False, indent=1))
