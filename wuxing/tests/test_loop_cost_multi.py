"""TDD · M3-3：成本多通道单价表——provider 类型 → 参考单价映射（多 API 估算失真修复）。"""
from wuxing.reporting import estimate_cost, price_table_for


def test_prices_per_provider():
    """四通道单价表存在且互不相同（deepseek/zhipu/anthropic/default）。"""
    for k in ("deepseek", "zhipu", "anthropic", "default"):
        t = price_table_for(k)
        assert "input" in t and "output" in t, f"{k} 表缺字段"
    assert price_table_for("deepseek") != price_table_for("zhipu"), "通道需独立表"


def test_spec_maps_to_table():
    """spec 映射：deepseek 字符串→deepseek 表；bigmodel dict→智谱表；anthropic→表。"""
    assert price_table_for("deepseek:deepseek-v4-flash") == price_table_for("deepseek")
    assert price_table_for({"type": "openai", "model": "glm-5.3-flash",
                            "base_url": "https://open.bigmodel.cn/api/paas/v4"}) == \
        price_table_for("zhipu"), "bigmodel base_url → 智谱通道"
    assert price_table_for("anthropic:claude-sonnet-4-5") == price_table_for("anthropic")
    assert price_table_for({"type": "openai", "model": "gpt-4o"}) == price_table_for("default")


def test_estimate_uses_channel_table():
    """估算按通道表：智谱表 vs DeepSeek 表结果应不同（同 usage）。"""
    usage = {"input": 1_000_000, "output": 500_000, "cache_read": 0,
             "cache_write": 0}
    ds = estimate_cost(usage, price_table_for("deepseek"))
    zp = estimate_cost(usage, price_table_for("zhipu"))
    assert ds != zp, "多通道单价必须影响估算"
    assert ds > 0 and zp > 0
