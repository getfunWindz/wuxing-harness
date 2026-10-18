"""G3：投影编辑恢复（restore=回到原文）+ 分支继承（设计 §5）。"""
import hashlib
import json


def _write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
                    + "\n", encoding="utf-8")


def _turn(rnd, text, digest=""):
    row = {"round": rnd, "user_text": text, "artifacts": [], "summary": "done",
           "ts": 1000.0 + rnd}
    if digest:
        row["fragment_digest"] = digest
    return row


def _md5(p):
    return hashlib.md5(p.read_bytes()).hexdigest()


def test_conversation_restore_reverts_omit(tmp_path):
    """省略轮 → 恢复 → 原文回来；对话文件零改写（审计保真）。"""
    from wuxing.conversation import ConversationState
    conv = tmp_path / ".wuxing" / "conversation-a.jsonl"
    _write(conv, [_turn(1, "第一轮"), _turn(2, "第二轮"), _turn(3, "第三轮")])
    side = tmp_path / ".wuxing" / "context-edits.jsonl"
    _write(side, [{"conversation": "conversation-a.jsonl", "round": 2,
                   "op": "omit", "ts": 1}])
    assert "第二轮" not in ConversationState(conv).context_text(max_chars=10000)
    before = _md5(conv)
    _write(side, [{"conversation": "conversation-a.jsonl", "round": 2,
                   "op": "omit", "ts": 1},
                  {"conversation": "conversation-a.jsonl", "round": 2,
                   "op": "restore", "ts": 2}])
    text = ConversationState(conv).context_text(max_chars=10000)
    assert "第二轮" in text
    assert _md5(conv) == before  # 对话文件零改写


def test_conversation_restore_then_replace_latest_wins(tmp_path):
    """顺序解析：omit→restore→replace 生效；replace→restore 回原文。"""
    from wuxing.conversation import ConversationState
    conv = tmp_path / ".wuxing" / "conversation-a.jsonl"
    _write(conv, [_turn(1, "第一轮"), _turn(2, "第二轮")])
    side = tmp_path / ".wuxing" / "context-edits.jsonl"
    base = {"conversation": "conversation-a.jsonl", "round": 2}
    _write(side, [{**base, "op": "omit", "ts": 1},
                  {**base, "op": "restore", "ts": 2},
                  {**base, "op": "replace", "content": "替换后文本", "ts": 3}])
    text = ConversationState(conv).context_text(max_chars=10000)
    assert "替换后文本" in text and "第二轮" not in text
    _write(side, [{**base, "op": "replace", "content": "替换后文本", "ts": 3},
                  {**base, "op": "restore", "ts": 4}])
    text2 = ConversationState(conv).context_text(max_chars=10000)
    assert "第二轮" in text2 and "替换后文本" not in text2


def test_conversation_restore_prev_digest_recovers(tmp_path):
    """被省略轮摘要不回流；恢复后回流。"""
    from wuxing.conversation import ConversationState
    conv = tmp_path / ".wuxing" / "conversation-a.jsonl"
    _write(conv, [_turn(1, "第一轮", "dig1"), _turn(2, "第二轮", "dig2")])
    side = tmp_path / ".wuxing" / "context-edits.jsonl"
    base = {"conversation": "conversation-a.jsonl", "round": 2}
    _write(side, [{**base, "op": "omit", "ts": 1}])
    assert ConversationState(conv).prev_digest() == "dig1"
    _write(side, [{**base, "op": "omit", "ts": 1},
                  {**base, "op": "restore", "ts": 2}])
    assert ConversationState(conv).prev_digest() == "dig2"


def test_load_unit_edits_restore_clears_target(tmp_path):
    """碎片编辑：restore 清除 (file,index) 项；再叠加再生效。"""
    from wuxing.context_sources import load_unit_edits
    side = tmp_path / ".wuxing" / "context-edits.jsonl"
    base = {"kind": "unit", "unit": "F-a", "file": "", "index": 1,
            "fp_in": "aa", "fp_out": "bb"}
    _write(side, [{**base, "op": "omit", "ts": 1}])
    assert len(load_unit_edits(tmp_path, "F-a")) == 1
    _write(side, [{**base, "op": "omit", "ts": 1},
                  {**base, "op": "restore", "ts": 2}])
    assert load_unit_edits(tmp_path, "F-a") == []
    _write(side, [{**base, "op": "omit", "ts": 1},
                  {**base, "op": "restore", "ts": 2},
                  {**base, "op": "replace", "content": "新内容", "ts": 3}])
    eff = load_unit_edits(tmp_path, "F-a")
    assert len(eff) == 1 and eff[0]["op"] == "replace"


def test_unit_restore_chain_omit_then_restore(tmp_path):
    """链路：装载 + 应用（省略生效 → 恢复后原文回来）。"""
    from wuxing.context_edits import apply_unit_edits
    from wuxing.context_sources import content_fp, load_unit_edits
    side = tmp_path / ".wuxing" / "context-edits.jsonl"
    fp = content_fp("原始内容")
    base = {"kind": "unit", "unit": "F-a", "file": "", "index": 0,
            "fp_in": fp, "fp_out": fp}
    msgs = [{"role": "user", "content": "原始内容"}]
    _write(side, [{**base, "op": "omit", "ts": 1}])
    out, _ = apply_unit_edits([dict(m) for m in msgs],
                              load_unit_edits(tmp_path, "F-a"))
    assert out == []  # 省略生效
    _write(side, [{**base, "op": "omit", "ts": 1},
                  {**base, "op": "restore", "ts": 2}])
    out2, skipped2 = apply_unit_edits([dict(m) for m in msgs],
                                      load_unit_edits(tmp_path, "F-a"))
    assert out2 == msgs and skipped2 == []  # 恢复后原文回来


# ---- Task 2：分支继承前缀编辑（G3 §2.2）----


def _conv_edit(name, round_no, op, ts, content=None):
    row = {"conversation": name, "round": round_no, "op": op, "ts": ts}
    if content is not None:
        row["content"] = content
    return row


def _branch_engine(tmp_path, edits):
    from wuxing.config import EngineConfig
    from wuxing.engine import Engine
    conv = tmp_path / ".wuxing" / "conversation-src.jsonl"
    _write(conv, [_turn(1, "第一轮"), _turn(2, "第二轮"), _turn(3, "第三轮")])
    if edits:
        _write(tmp_path / ".wuxing" / "context-edits.jsonl", edits)
    return Engine(cfg=EngineConfig(), workdir=tmp_path, auto_confirm=True)


def _sidecar_rows(tmp_path):
    p = tmp_path / ".wuxing" / "context-edits.jsonl"
    if not p.is_file():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip()]


def test_branch_inherits_prefix_edits_continue_boundary(tmp_path):
    """continue K=N：轮 ≤ K 复制；分支点后（轮 3）不复制。"""
    from wuxing.conversation import ConversationState
    src = "conversation-src.jsonl"
    edits = [_conv_edit(src, 1, "omit", 1),
             _conv_edit(src, 2, "replace", 2, content="替换二"),
             _conv_edit(src, 3, "omit", 3)]
    eng = _branch_engine(tmp_path, edits)
    res = eng.branch_conversation(src, 2, mode="continue", summary="none")
    text = ConversationState(tmp_path / ".wuxing" / res["session"]).context_text(
        max_chars=10000)
    assert "第一轮" not in text
    assert "替换二" in text and "第二轮" not in text
    assert "第三轮" not in text  # 轮 3 属被放弃尾部（未复制）——其编辑也不应出现
    mine = [r for r in _sidecar_rows(tmp_path)
            if r["conversation"] == res["session"]]
    assert sorted(r["round"] for r in mine) == [1, 2]


def test_branch_redo_boundary(tmp_path):
    """redo K=N-1：仅轮 ≤ N-1 复制。"""
    src = "conversation-src.jsonl"
    edits = [_conv_edit(src, 1, "omit", 1),
             _conv_edit(src, 2, "replace", 2, content="替换二")]
    eng = _branch_engine(tmp_path, edits)
    res = eng.branch_conversation(src, 2, mode="redo", summary="none")
    mine = [r for r in _sidecar_rows(tmp_path)
            if r["conversation"] == res["session"]]
    assert sorted(r["round"] for r in mine) == [1]


def test_branch_inherits_restore_records_in_order(tmp_path):
    """restore 记录按序复制——分支终态 = 源终态。"""
    from wuxing.conversation import ConversationState
    src = "conversation-src.jsonl"
    edits = [_conv_edit(src, 1, "omit", 1),
             _conv_edit(src, 1, "restore", 2),
             _conv_edit(src, 2, "replace", 3, content="替换二")]
    eng = _branch_engine(tmp_path, edits)
    res = eng.branch_conversation(src, 3, mode="continue", summary="none")
    mine = [r["op"] for r in _sidecar_rows(tmp_path)
            if r["conversation"] == res["session"]]
    assert mine == ["omit", "restore", "replace"]
    text = ConversationState(tmp_path / ".wuxing" / res["session"]).context_text(
        max_chars=10000)
    assert "第一轮" in text  # restore 终态：原文回来


def test_branch_edits_isolated_from_source(tmp_path):
    """双向隔离：分支内编辑不回写源；源后续编辑不影响分支。"""
    from wuxing.conversation import ConversationState
    src = "conversation-src.jsonl"
    eng = _branch_engine(tmp_path, [_conv_edit(src, 1, "omit", 1)])
    res = eng.branch_conversation(src, 3, mode="continue", summary="none")
    # 分支内新增编辑
    side = tmp_path / ".wuxing" / "context-edits.jsonl"
    side.write_text(side.read_text(encoding="utf-8")
                    + json.dumps(_conv_edit(res["session"], 2, "replace", 99,
                                            content="分支内替换"),
                                 ensure_ascii=False) + "\n", encoding="utf-8")
    src_text = ConversationState(tmp_path / ".wuxing" / src).context_text(
        max_chars=10000)
    assert "第二轮" in src_text and "分支内替换" not in src_text
    # 源后续编辑不影响分支
    side.write_text(side.read_text(encoding="utf-8")
                    + json.dumps(_conv_edit(src, 3, "omit", 100),
                                 ensure_ascii=False) + "\n", encoding="utf-8")
    br_text = ConversationState(tmp_path / ".wuxing" / res["session"]).context_text(
        max_chars=10000)
    assert "第三轮" in br_text
    assert "分支内替换" in br_text  # 分支内编辑留在分支


def test_branch_without_edits_no_copy(tmp_path):
    """源无编辑 → 不产生新会话编辑记录。"""
    eng = _branch_engine(tmp_path, None)
    res = eng.branch_conversation("conversation-src.jsonl", 3, mode="redo",
                                  summary="none")
    assert all(r.get("conversation") != res["session"]
               for r in _sidecar_rows(tmp_path))
