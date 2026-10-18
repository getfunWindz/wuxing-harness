"""G1 对话分支基元测试（设计 §7.1：承接行/机械摘要/命名）。"""
import json


def _write_turns(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
                    + "\n", encoding="utf-8")


def _turn(rnd, text="任务", summary="done", **kw):
    row = {"round": rnd, "user_text": text, "artifacts": [],
           "summary": summary, "ts": 1000.0 + rnd}
    row.update(kw)
    return row


def _branch_row(**kw):
    row = {"type": "branch", "source": "conversation-a.jsonl",
           "from_round": 2, "mode": "redo", "summary_mode": "mech",
           "summary": "被放弃路径小结", "focus": "", "ts": 2000.0}
    row.update(kw)
    return row


def test_branch_row_not_counted_in_round_no(tmp_path):
    """承接行不占轮次号（round_no 只计含 round 键的行）。"""
    from wuxing.conversation import ConversationState
    p = tmp_path / "conversation-x.jsonl"
    _write_turns(p, [_turn(1), _branch_row(), _turn(2)])
    assert ConversationState(p).round_no == 2


def test_context_text_injects_branch_block_at_position(tmp_path):
    """承接块位于分支点（轮 1 之后、轮 2 之前）。"""
    from wuxing.conversation import ConversationState
    p = tmp_path / "conversation-x.jsonl"
    _write_turns(p, [_turn(1, "第一轮"), _branch_row(summary="旧路径小结"),
                     _turn(2, "第二轮")])
    text = ConversationState(p).context_text(max_chars=10000)
    assert "[分支承接]" in text
    assert text.index("第1轮") < text.index("[分支承接]") < text.index("第2轮")
    assert "旧路径小结" in text
    assert "重做" in text  # mode 中文标注


def test_context_text_skips_branch_block_when_summary_empty(tmp_path):
    """摘要为空（none 模式）→ 不注入上下文块。"""
    from wuxing.conversation import ConversationState
    p = tmp_path / "conversation-x.jsonl"
    _write_turns(p, [_branch_row(summary=""), _turn(1)])
    assert "[分支承接]" not in ConversationState(p).context_text(max_chars=10000)


def test_prev_digest_and_turn_views_skip_branch_rows(tmp_path):
    """既有读取面：prev_digest/turn_views 不把承接行当轮次。"""
    from wuxing.conversation import ConversationState
    p = tmp_path / "conversation-x.jsonl"
    _write_turns(p, [_turn(1, fragment_digest="dig1"), _branch_row(),
                     _turn(2, fragment_digest="dig2")])
    st = ConversationState(p)
    assert st.prev_digest() == "dig2"
    assert [v["round"] for v in st.turn_views()] == [1, 2]


def test_build_branch_digest_deterministic_and_truncated():
    """机械摘要：确定性 + 上限截断。"""
    from wuxing.conversation import build_branch_digest
    turns = [_turn(3, "实现登录接口", "done；交付 a.py"),
             _turn(4, "补充测试" * 50, "failed")]
    d1 = build_branch_digest(turns, max_chars=2000)
    d2 = build_branch_digest(turns, max_chars=2000)
    assert d1 == d2
    assert "第3轮" in d1 and "第4轮" in d1 and "a.py" in d1
    small = build_branch_digest(turns, max_chars=60)
    assert len(small) <= 60
    assert small.endswith("…")


def test_new_conversation_name_conflict_suffix(tmp_path, monkeypatch):
    """命名与壳同口径：conversation-<ts>.jsonl，冲突加序。"""
    from wuxing import conversation
    monkeypatch.setattr(conversation.time, "time", lambda: 111)
    (tmp_path / "conversation-111.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "conversation-111-2.jsonl").write_text("", encoding="utf-8")
    assert conversation.new_conversation_name(tmp_path) == \
        "conversation-111-3.jsonl"


def test_append_turn_numbering_after_branch(tmp_path):
    """承接行后 append_turn 编号延续（redo=前缀轮数+1）。"""
    from wuxing.conversation import ConversationState
    p = tmp_path / "conversation-x.jsonl"
    _write_turns(p, [_turn(1), _turn(2), _branch_row()])
    st = ConversationState(p)
    row = st.append_turn(st.round_no + 1, "修正后的指令", [])
    assert row["round"] == 3


# ---- Task 2：Engine.branch_conversation（派生会话/摘要/血缘）----


def _make_engine(tmp_path, llm=None):
    from wuxing.config import EngineConfig
    from wuxing.engine import Engine
    return Engine(cfg=EngineConfig(), workdir=tmp_path, auto_confirm=True,
                  llm=llm)


def _src_rows():
    return [_turn(1, "第一轮", "done；交付 a.py"),
            _turn(2, "第二轮", "done"),
            _turn(3, "第三轮", "done", unit="F-a"),
            _turn(4, "第四轮", "failed")]


class _FakeLlm:
    def __init__(self, text="LLM 摘要：尝试了 X，结论 Y"):
        self.text = text
        self.calls = []

    def spec(self): return "deepseek:fake-branch"
    def name(self): return "fake-branch"
    def supports_native_tools(self): return True

    def chat(self, messages, tools=None):
        self.calls.append(messages)
        return self.text


def test_branch_redo_prefix_bytes_identical_and_unit_copied(tmp_path):
    src = tmp_path / ".wuxing" / "conversation-src.jsonl"
    _write_turns(src, _src_rows())
    res = _make_engine(tmp_path).branch_conversation(
        "conversation-src.jsonl", 4, mode="redo")
    new_path = tmp_path / ".wuxing" / res["session"]
    src_lines = [l for l in src.read_text(encoding="utf-8").splitlines()
                 if l.strip()]
    new_lines = [l for l in new_path.read_text(encoding="utf-8").splitlines()
                 if l.strip()]
    assert new_lines[:3] == src_lines[:3]  # 前缀字节一致（含碎片行）
    parsed = [json.loads(l) for l in new_lines]
    assert [r.get("round") for r in parsed if "round" in r] == [1, 2, 3]
    assert parsed[2].get("unit") == "F-a"
    assert parsed[-1]["type"] == "branch"
    assert parsed[-1]["summary_mode"] == "mech"
    assert res["redo_text"] == "第四轮"
    assert res["abandoned_rounds"] == 1
    assert res["summary_mode"] == "mech" and "第4轮" in res["summary"]


def test_branch_continue_prefix_and_numbering(tmp_path):
    from wuxing.conversation import ConversationState
    src = tmp_path / ".wuxing" / "conversation-src.jsonl"
    _write_turns(src, _src_rows())
    res = _make_engine(tmp_path).branch_conversation(
        "conversation-src.jsonl", 2, mode="continue")
    st = ConversationState(tmp_path / ".wuxing" / res["session"])
    assert st.round_no == 2
    assert st.append_turn(st.round_no + 1, "新方向", [])["round"] == 3
    assert res["abandoned_rounds"] == 2  # 第 3（碎片）/4 轮被放弃
    assert "redo_text" not in res


def test_branch_redo_numbering_continues_at_branch_point(tmp_path):
    from wuxing.conversation import ConversationState
    src = tmp_path / ".wuxing" / "conversation-src.jsonl"
    _write_turns(src, _src_rows())
    res = _make_engine(tmp_path).branch_conversation(
        "conversation-src.jsonl", 2, mode="redo")
    st = ConversationState(tmp_path / ".wuxing" / res["session"])
    assert st.round_no == 1
    assert st.append_turn(st.round_no + 1, "修正", [])["round"] == 2


def test_branch_summary_none_no_injection(tmp_path):
    from wuxing.conversation import ConversationState
    src = tmp_path / ".wuxing" / "conversation-src.jsonl"
    _write_turns(src, _src_rows())
    res = _make_engine(tmp_path).branch_conversation(
        "conversation-src.jsonl", 4, summary="none")
    assert res["summary_mode"] == "none" and res["summary"] == ""
    text = ConversationState(tmp_path / ".wuxing" / res["session"]).context_text(
        max_chars=10000)
    assert "[分支承接]" not in text


def test_branch_llm_summary_with_fake_provider(tmp_path):
    fake = _FakeLlm()
    src = tmp_path / ".wuxing" / "conversation-src.jsonl"
    _write_turns(src, _src_rows())
    res = _make_engine(tmp_path, llm=fake).branch_conversation(
        "conversation-src.jsonl", 2, summary="llm", focus="关注安全性")
    assert res["summary_mode"] == "llm"
    assert res["summary"].startswith("LLM 摘要")
    assert fake.calls and "关注安全性" in json.dumps(fake.calls,
                                                     ensure_ascii=False)


def test_branch_llm_degrades_to_mech_when_mock(tmp_path):
    src = tmp_path / ".wuxing" / "conversation-src.jsonl"
    _write_turns(src, _src_rows())
    res = _make_engine(tmp_path).branch_conversation(
        "conversation-src.jsonl", 2, summary="llm")
    assert res["summary_mode_requested"] == "llm"
    assert res["summary_mode"] == "mech"
    assert "第4轮" in res["summary"]


def test_branch_errors(tmp_path):
    import pytest
    src = tmp_path / ".wuxing" / "conversation-src.jsonl"
    _write_turns(src, _src_rows())
    eng = _make_engine(tmp_path)
    with pytest.raises(ValueError):
        eng.branch_conversation("conversation-none.jsonl", 1)
    with pytest.raises(ValueError):
        eng.branch_conversation("conversation-src.jsonl", 99)
    with pytest.raises(ValueError):
        eng.branch_conversation("conversation-src.jsonl", 3)  # 碎片轮
    with pytest.raises(ValueError):
        eng.branch_conversation("conversation-src.jsonl", 1, mode="x")
    with pytest.raises(ValueError):
        eng.branch_conversation("conversation-src.jsonl", 1, summary="x")
    with pytest.raises(ValueError):
        eng.branch_conversation("../evil.jsonl", 1)


def test_branch_lineage_sidecar_recorded(tmp_path):
    src = tmp_path / ".wuxing" / "conversation-src.jsonl"
    _write_turns(src, _src_rows())
    res = _make_engine(tmp_path).branch_conversation(
        "conversation-src.jsonl", 4, mode="redo")
    side = tmp_path / ".wuxing" / "branches.jsonl"
    rows = [json.loads(l) for l in side.read_text(encoding="utf-8").splitlines()
            if l.strip()]
    assert rows and rows[-1]["conversation"] == res["session"]
    assert rows[-1]["source"] == "conversation-src.jsonl"
    assert rows[-1]["from_round"] == 4


def test_branch_of_branch_keeps_leading_branch_row(tmp_path):
    src = tmp_path / ".wuxing" / "conversation-src.jsonl"
    _write_turns(src, _src_rows())
    eng = _make_engine(tmp_path)
    r1 = eng.branch_conversation("conversation-src.jsonl", 2, mode="continue")
    r2 = eng.branch_conversation(r1["session"], 1, mode="redo")
    assert r2["session"] != r1["session"]
    rows = [json.loads(l) for l in
            (tmp_path / ".wuxing" / r2["session"]).read_text(
                encoding="utf-8").splitlines() if l.strip()]
    assert rows[0]["type"] == "branch"  # K=0：保留文件头部承接行
    assert rows[-1]["type"] == "branch"
