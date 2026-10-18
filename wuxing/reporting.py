"""报告与指标（P5 拆分：从 engine.py 提取——职责内聚）。

build_report：任务报告文本（缓存/成本段——P1 T4）。
estimate_cost：usage 真值 → 成本估算（单价表驱动——未配单价返回 0）。
"""

# 参考单价（元/百万 token；表驱动——多通道独立单价，M3-3）
# DeepSeek 官方参考价；未匹配通道走 default（保守：未命中 1 元/命中 0.1/输出 2）
DEFAULT_PRICES = {"input": 1.0, "cache_read": 0.1, "output": 2.0}

# M3-3：多通道单价表（元/百万 token——各 API 官方参考价；表驱动可扩展）
PRICE_TABLES = {
    "deepseek": {"input": 1.0, "cache_read": 0.1, "output": 2.0},
    # 智谱 GLM 官方（大模型定价——flash 档参考）
    "zhipu": {"input": 0.5, "cache_read": 0.1, "output": 1.5},
    # Anthropic（Sonnet 档参考）
    "anthropic": {"input": 15.0, "cache_read": 1.5, "output": 75.0},
}


def price_table_for(spec) -> dict:
    """provider spec（str/dict/表名）→ 参考单价表（M3-3 多通道映射）。

    - 字符串 "type:model" → type；"deepseek" 等表名直通
    - dict：type=anthropic → anthropic；base_url 含 bigmodel → zhipu；
      type=deepseek → deepseek；其余 openai 兼容 → default
    """
    if isinstance(spec, str):
        if spec in PRICE_TABLES:
            return PRICE_TABLES[spec]
        ptype = spec.split(":", 1)[0] if ":" in spec else spec
        return PRICE_TABLES.get(ptype, DEFAULT_PRICES)
    if isinstance(spec, dict):
        ptype = spec.get("type", "")
        base = str(spec.get("base_url", ""))
        if "bigmodel.cn" in base:
            return PRICE_TABLES["zhipu"]
        if ptype == "anthropic":
            return PRICE_TABLES["anthropic"]
        if ptype == "deepseek":
            return PRICE_TABLES["deepseek"]
    return DEFAULT_PRICES


def compute_usage_metrics(usage: dict) -> dict:
    """命中率细分——服务端缓存效率分诊（缓存问题 vs 模型能力问题第一诊断）。

    cache_read_ratio：服务端缓存读占输入比（=0 且长会话 → 布局/前缀问题）
    save_tokens/save_cost：缓存节省（折扣价 vs 全价差）
    """
    inp = usage.get("input", 0) or 0
    cr = usage.get("cache_read", 0) or 0
    p = DEFAULT_PRICES
    full = inp * p["input"]
    actual = cr * p["cache_read"] + (inp - cr) * p["input"]
    return {
        "cache_read_ratio": round(cr / inp, 4) if inp else 0.0,
        "save_tokens": cr,
        "save_cost": round((full - actual) / 1_000_000, 4),
    }


# 契约报告 kind（与 engine.Engine._REPORT_KINDS 同源——归档与用户面过滤用
# 同一集合；测试守同步：test_loop_cost.test_report_internal_kinds_in_sync_with_engine）
_INTERNAL_KINDS = ("plan", "result", "verdict", "acceptance")


def _user_visible(artifacts) -> list:
    """用户面产物：滤除内部产物（契约报告 + .wuxing/ 路径——Task A4）。

    用户裁决 2026-10-01：F-* 中间产物不得出现在用户可见面；工作区真实
    交付物（write_file 产物）不受影响。模型仍可经 .wuxing/reports/ 读回。
    真机补充（2026-10-03）：报告生成于归档**前**——契约报告彼时为裸路径
    （F-0001-result.md）且 kind 为契约类型；过滤须与归档同源（kind），
    否则归档前形态漏进报告详情。
    """
    out = []
    for a in artifacts or []:
        p = str(getattr(a, "path", "") or "").replace("\\", "/")
        if p.startswith(".wuxing/"):
            continue
        if str(getattr(a, "kind", "") or "") in _INTERNAL_KINDS:
            continue
        out.append(a)
    return out


_CLASS_LABEL = {"provider": "基础设施失败（provider）",
                "budget": "预算耗尽（budget）",
                "stalled": "无进展早停（stalled）"}


def build_report(units, artifacts, metrics=None) -> str:
    lines = ["# 任务执行报告", ""]
    unpassed = []
    for u in units:
        mark = ""
        if getattr(u, "verdict_fail", False):
            mark = "（验收结论：不通过）"
            unpassed.append(u.unit_id)
        _fc = getattr(u, "failure_class", "") or ""
        if _fc in _CLASS_LABEL:
            mark += f"（{_CLASS_LABEL[_fc]}）"
        lines.append(f"- {u.unit_id} [{u.domain_id}] {u.status}{mark}")
    _fails = {"provider": 0, "budget": 0, "stalled": 0}
    for u in units:
        _fc = getattr(u, "failure_class", "") or ""
        if _fc in _fails:
            _fails[_fc] += 1
    _parts = []
    if _fails["provider"]:
        _parts.append(f"基础设施 {_fails['provider']}（可重跑）")
    if _fails["budget"]:
        _parts.append(f"预算 {_fails['budget']}")
    if _fails["stalled"]:
        _parts.append(f"停滞 {_fails['stalled']}")
    if _parts:
        lines.append("\n失败构成：" + " · ".join(_parts))
    if unpassed:
        lines.append(f"\n## 验收结论\n- 验收不通过：{'、'.join(unpassed)}——任务状态降级（产物未达标准，机制裁决）")
    visible = _user_visible(artifacts)
    lines.append(f"\n产物 {len(visible)} 个：")
    for a in visible:
        lines.append(f"  - {a.path} ({a.kind})")
    if metrics:
        c = metrics.get("cache", {})
        u = metrics.get("usage", {})
        lines.append("\n## 缓存与成本")
        lines.append(f"- LLM 调用：{metrics.get('llm_calls', 0)} 次")
        lines.append(
            f"- 回复缓存：命中 {c.get('reply', {}).get('hits', 0)} / "
            f"未中 {c.get('reply', {}).get('misses', 0)} "
            f"（语义命中 {c.get('reply', {}).get('similar_hits', 0)}）")
        lines.append(
            f"- 形状化缓存：命中 {c.get('shape', {}).get('hits', 0)} / "
            f"未中 {c.get('shape', {}).get('misses', 0)}")
        lines.append(
            f"- Token 真值：输入 {u.get('input', 0)} 输出 {u.get('output', 0)} "
            f"缓存读 {u.get('cache_read', 0)} 缓存写 {u.get('cache_write', 0)}")
        um = compute_usage_metrics(u)
        lines.append(
            f"- 服务端缓存读占比：{um['cache_read_ratio'] * 100:.1f}% "
            f"（节省 {um['save_tokens']} tokens，约 {um['save_cost']:.4f} 元）")
        bd = metrics.get("breakdown", {})
        if bd:
            lines.append(
                f"- 语义命中质量：{bd.get('semantic_hits', 0)} 次命中 / "
                f"{bd.get('semantic_ok', 0)} 次成功"
                f"（误命中检测——语义命中后单元应成功）")
            lines.append(
                f"- 失效结构：首轮 miss {bd.get('first_round_misses', 0)}（新任务正常）/ "
                f"后续轮 miss {bd.get('later_round_misses', 0)}（异常应为 0——毒化残留）")
        cost = estimate_cost(u)
        if cost > 0:
            lines.append(f"- 估算成本：{cost:.4f} 元（参考单价表）")
    return "\n".join(lines)


def estimate_cost(usage: dict, prices: dict | None = None) -> float:
    """usage 真值（token）→ 成本估算（元）；单位：每百万 token。"""
    p = dict(DEFAULT_PRICES if prices is None else prices)
    total = 0.0
    total += usage.get("input", 0) * p.get("input", 0)
    total += usage.get("cache_read", 0) * p.get("cache_read", 0)
    total += usage.get("output", 0) * p.get("output", 0)
    return total / 1_000_000
