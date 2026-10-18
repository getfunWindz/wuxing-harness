from scripts.cache_plan_diag import summarize


def _call(domain="plan", input_tokens=1000, cache_read=100):
    return {"event": "llm_call", "domain": domain,
            "input": input_tokens, "cache_read": cache_read}


def _sections(contract="c", domain="d", tools="t", budget="b"):
    return {"event": "prompt_sections", "domain": "plan",
            "hashes": {"sys:contract": contract, "sys:domain": domain,
                       "sys:tools": tools, "sys:budget": budget}}


def test_summarize_counts_and_stable_system_prefix():
    rows = [_call(), _call(input_tokens=500, cache_read=50),
            _sections(), _sections()]
    out = summarize(rows)
    assert out["plan_calls"] == 2
    assert out["input_tokens"] == 1500
    assert out["cache_read_tokens"] == 150
    assert out["ratio"] == 0.1
    assert out["plan_prompt_sections"] == 2
    assert out["system_hash_distinct"] == {
        "sys:contract": 1, "sys:domain": 1, "sys:tools": 1, "sys:budget": 1}


def test_summarize_detects_changed_section():
    rows = [_sections(budget="b1"), _sections(budget="b2")]
    out = summarize(rows)
    assert out["system_hash_distinct"]["sys:budget"] == 2
    assert out["system_combo_count"] == 2
    assert out["plan_calls"] == 0
