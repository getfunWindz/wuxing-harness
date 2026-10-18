"""TDD：A3 窗口预算与确定性优先级裁剪（无预算=现状；超限按固定优先级）。"""
from wuxing.context_budget import enforce_budget, trim_text_tail
from wuxing.context_preview import estimate_tokens


def _msg(role, content):
    return {"role": role, "content": content}


def test_no_budget_returns_unchanged():
    msgs = [_msg("system", "S"), _msg("user", "[会话历史]\n第1轮：x")]
    out, trimmed = enforce_budget(msgs, 0, estimate_tokens)
    assert out == msgs and trimmed == []


def test_digest_dropped_before_history():
    msgs = [
        _msg("system", "S"),
        _msg("user", "[会话历史]\n第1轮：一轮需求内容"),
        _msg("user", "[上一轮碎片上下文]\n" + "摘" * 200),
        _msg("user", "任务提示"),
    ]
    out, trimmed = enforce_budget(msgs, 300, estimate_tokens)
    keys = [t["key"] for t in trimmed]
    assert "digest" in keys and "history" not in keys, trimmed
    assert not any(str(m["content"]).startswith("[上一轮碎片上下文]")
                   for m in out)


def test_history_shrinks_from_oldest_and_keeps_prompt():
    msgs = [_msg("system", "S"),
            _msg("user", "[会话历史]\n" + "旧" * 500),
            _msg("user", "任务提示")]
    out, trimmed = enforce_budget(msgs, 300, estimate_tokens)
    assert any(t["key"] == "history" for t in trimmed), trimmed
    hist = next(m for m in out if str(m["content"]).startswith("[会话历史]"))
    assert estimate_tokens(hist["content"]) <= 300
    assert out[-1]["content"] == "任务提示"


def test_prefix_oldest_removed_keeps_system_prompt_and_skills():
    msgs = [_msg("system", "S")]
    msgs += [_msg("assistant", f"前缀消息{i}" + "x" * 50) for i in range(5)]
    msgs += [_msg("user", "任务提示"),
             _msg("user", "可用技能：（详情按需 load_skill）")]
    out, trimmed = enforce_budget(msgs, 200, estimate_tokens)
    assert any(t["key"] == "prefix" for t in trimmed), trimmed
    assert out[0]["role"] == "system"
    assert len(out) < len(msgs)
    assert any(str(m["content"]) == "任务提示" for m in out)
    assert any(str(m["content"]).startswith("可用技能：") for m in out)


def test_trim_text_tail_keeps_tail_and_respects_budget():
    text = "A" * 100 + "B" * 20
    out, cut = trim_text_tail(text, 30, estimate_tokens)
    assert out.endswith("B" * 20) and cut > 0
    assert estimate_tokens(out) <= 30


def test_config_budget_default_and_schema_double_write():
    from wuxing.config import EngineConfig
    from wuxing.config_schema import FIELD_SPECS
    assert EngineConfig().context_budget_tokens == 0
    assert "context_budget_tokens" in {s.name for s in FIELD_SPECS}


def test_enforce_budget_indexed_maps_duplicates_by_original_index():
    """精化：索引映射——同内容消息各归其位（预览 FSC 前缀映射用）。"""
    from wuxing.context_budget import enforce_budget_indexed
    dup = "重复" * 10
    msgs = [_msg("user", dup), _msg("user", dup), _msg("user", "任务提示")]
    out, trimmed, kept = enforce_budget_indexed(msgs, 70, estimate_tokens)
    assert kept == [1, 2], kept
    assert [m["content"] for m in out] == [dup, "任务提示"]
    assert any(t["key"] == "prefix" for t in trimmed), trimmed
