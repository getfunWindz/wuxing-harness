"""TDD · 会话状态模型（B 模式：append-only 历史 + 交付物累计 + 确定性上下文段）。"""
import pathlib
import tempfile

from wuxing.conversation import ConversationState


def test_conversation_append_and_persist():
    """轮次追加 + JSONL 往返（append-only——前缀只增不改的持久化基础）。"""
    p = pathlib.Path(tempfile.mkdtemp()) / "conv.jsonl"
    st = ConversationState(p)
    st.append_turn(round_no=1, user_text="实现登录", artifacts=["a.py"],
                   summary="已完成登录页")
    st.append_turn(round_no=2, user_text="再加记住我", artifacts=["b.py"],
                   summary="已加记住我")
    st2 = ConversationState(p)
    assert len(st2.turns) == 2
    assert st2.turns[0]["user_text"] == "实现登录"
    assert st2.artifacts() == ["a.py", "b.py"]
    assert st2.round_no == 2


def test_conversation_context_text_stable_and_capped():
    """会话段文本：同状态同输出（确定性）+ 上限裁剪（保留最近轮次）。"""
    p = pathlib.Path(tempfile.mkdtemp()) / "conv.jsonl"
    st = ConversationState(p)
    for i in range(1, 6):
        st.append_turn(round_no=i, user_text=f"需求{i}" * 200,
                       artifacts=[f"f{i}.py"], summary=f"第{i}轮完成")
    t1 = st.context_text(max_chars=600)
    t2 = st.context_text(max_chars=600)
    assert t1 == t2 and len(t1) <= 600
    assert "第5轮完成" in t1 and "第1轮完成" not in t1  # 最近轮次优先


def test_context_text_meta_fold_count():
    """S5-B（A13）：折叠元数据机械化——context_text_meta 返回 (text, folded)。"""
    p = pathlib.Path(tempfile.mkdtemp()) / "conv.jsonl"
    st = ConversationState(p)
    for i in range(1, 6):
        st.append_turn(round_no=i, user_text=f"需求{i}" * 200,
                       artifacts=[f"f{i}.py"], summary=f"第{i}轮完成")
    text, folded = st.context_text_meta(max_chars=600)
    assert folded >= 1
    assert "已折叠" in text
    assert st.context_text(max_chars=600) == text          # 兼容转出
    text2, folded2 = st.context_text_meta(max_chars=10_000_000)
    assert folded2 == 0 and "已折叠" not in text2
    assert st.context_text(max_chars=10_000_000) == text2


def test_conversation_empty_and_corrupt_tolerant():
    """空状态 → 空串；损坏行跳过（韧性惯例）。"""
    p = pathlib.Path(tempfile.mkdtemp()) / "conv.jsonl"
    assert ConversationState(p).context_text() == ""
    p.write_text("{corrupt\n" + '{"round": 1, "user_text": "ok", "artifacts": [],'
                 ' "summary": ""}\n', encoding="utf-8")
    st = ConversationState(p)
    assert st.round_no == 1
    assert "ok" in st.context_text()


def test_context_text_prefix_append_only():
    """红线验证：追加新轮次后，旧轮次的文本块仍是新前缀的**前缀部分**
    （前缀只增不改——服务端缓存命中前提）。"""
    p = pathlib.Path(tempfile.mkdtemp()) / "conv.jsonl"
    st = ConversationState(p)
    st.append_turn(1, "第一轮需求", ["a.py"], "完成1")
    first = st.context_text(max_chars=4000)
    st.append_turn(2, "第二轮需求", ["b.py"], "完成2")
    second = st.context_text(max_chars=4000)
    # 第一轮的块必须在第二轮文本中原样保留（位置前移——追加在尾部）
    assert first.replace("[会话历史]\n", "") in second


def test_context_text_includes_artifact_excerpts():
    """B2：产物摘录进上下文段（跨轮继承原料——前缀只追加）。"""
    p = pathlib.Path(tempfile.mkdtemp()) / "conv.jsonl"
    st = ConversationState(p)
    st.append_turn(round_no=1, user_text="实现登录", artifacts=["a.md"],
                   summary="完成", artifact_excerpts=[
                       {"path": "a.md", "excerpt": "登录页实现：JWT 校验中间件…"}])
    text = st.context_text()
    assert "登录页实现：JWT 校验中间件" in text, \
        f"产物摘录必须进上下文（跨轮继承）：{text}"
    # 持久化往返
    st2 = ConversationState(p)
    assert "登录页实现" in st2.context_text()


def test_context_excerpt_capped():
    """B2：摘录有界——超长摘录截断（防上下文无界膨胀）。"""
    p = pathlib.Path(tempfile.mkdtemp()) / "conv.jsonl"
    st = ConversationState(p)
    st.append_turn(1, "t", ["a.md"], "s",
                   artifact_excerpts=[{"path": "a.md", "excerpt": "X" * 5000}])
    text = st.context_text(max_chars=4000)
    assert len(text) <= 4000


def test_unit_marked_turns_excluded_from_context():
    """碎片会话轮次（unit 标记）不得计入主会话上下文窗口（用户 2026-09-21 硬要求）。"""
    p = pathlib.Path(tempfile.mkdtemp()) / "conv.jsonl"
    st = ConversationState(p)
    st.append_turn(1, "主会话第一轮", ["a.py"], "完成1")
    st.append_turn(2, "碎片内提交", ["b.py"], "碎片完成", unit="P-a")
    st.append_turn(3, "主会话第二轮", [], "完成3")
    text = st.context_text(max_chars=4000)
    assert "主会话第一轮" in text and "主会话第二轮" in text
    assert "碎片内提交" not in text, "碎片轮次不得进入 context_text"
    # 持久化往返：重载后仍隔离（且无标记轮次不落 unit 键——旧行字节不变）
    st2 = ConversationState(p)
    assert st2.turns[1].get("unit") == "P-a"
    assert "unit" not in st2.turns[0]
    assert "碎片内提交" not in st2.context_text(max_chars=4000)


def test_unit_marked_turn_not_used_as_prev_digest():
    """FSC 回退摘要是上下文前缀的一部分——同样不得注入碎片轮次。"""
    p = pathlib.Path(tempfile.mkdtemp()) / "conv.jsonl"
    st = ConversationState(p)
    st.append_turn(1, "主轮", [], "完成1", fragment_digest="主摘要")
    st.append_turn(2, "碎片轮", [], "碎片", fragment_digest="碎片摘要", unit="P-a")
    assert st.prev_digest() == "主摘要"


def test_context_edits_omit_replace_latest_wins():
    """编辑层（B 期）：omit/replace 仅投影生效；日志零改写；同轮最新生效。"""
    p = pathlib.Path(tempfile.mkdtemp()) / "conversation-1.jsonl"
    st = ConversationState(p)
    st.append_turn(1, "原始一", ["a.py"], "s1")
    st.append_turn(2, "原始二", [], "s2")
    st.append_turn(3, "原始三", [], "s3")
    before = p.read_text(encoding="utf-8")
    (p.parent / "context-edits.jsonl").write_text(
        '{"conversation": "conversation-1.jsonl", "round": 2, "op": "omit", "ts": 1}\n'
        '{"conversation": "conversation-1.jsonl", "round": 3, "op": "replace", "content": "改写三", "ts": 2}\n'
        '{"conversation": "conversation-1.jsonl", "round": 1, "op": "omit", "ts": 3}\n'
        '{"conversation": "conversation-1.jsonl", "round": 1, "op": "replace", "content": "最终一", "ts": 4}\n'
        'not-json（坏行跳过）\n'
        '{"conversation": "other.jsonl", "round": 2, "op": "replace", "content": "错误改写", "ts": 5}\n',
        encoding="utf-8")
    st2 = ConversationState(p)
    text = st2.context_text(max_chars=4000)
    assert "改写三" in text and "原始三" not in text
    assert "最终一" in text and "原始一" not in text   # 最新生效（replace 覆盖 omit）
    assert "原始二" not in text                       # omit
    assert "错误改写" not in text   # 其他会话的编辑不影响本文件
    assert p.read_text(encoding="utf-8") == before     # 日志零改写
    views = {v["round"]: v for v in st2.turn_views()}
    assert views[2]["omitted"] is True and views[2]["replaced"] is False
    assert views[3]["replaced"] is True and views[3]["omitted"] is False


def test_prev_digest_skips_omitted_turns():
    p = pathlib.Path(tempfile.mkdtemp()) / "conversation-1.jsonl"
    st = ConversationState(p)
    st.append_turn(1, "一", [], "s1", fragment_digest="摘要一")
    st.append_turn(2, "二", [], "s2", fragment_digest="摘要二")
    st.append_turn(3, "三", [], "s3", fragment_digest="摘要三")
    (p.parent / "context-edits.jsonl").write_text(
        '{"conversation": "conversation-1.jsonl", "round": 3, "op": "omit", "ts": 1}\n'
        '{"conversation": "conversation-1.jsonl", "round": 2, "op": "omit", "ts": 2}\n',
        encoding="utf-8")
    assert ConversationState(p).prev_digest() == "摘要一"
