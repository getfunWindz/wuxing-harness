"""TDD（双模式批 4 · Task 1）：承接简报——轮次/产物/地图/截断/缺失。"""


def test_brief_rounds_artifacts_and_map(tmp_path):
    from wuxing.conversation import ConversationState
    from wuxing.handoff import build_brief
    from wuxing.map_doc import write_sections
    conv = tmp_path / ".wuxing" / "conversation-1.jsonl"
    st = ConversationState(conv)
    st.append_turn(1, "先做一个发布工具", ["artifacts/a.md"], "完成 A")
    st.append_turn(2, "再加一个校验", ["artifacts/b.md", "artifacts/a.md"], "完成 B")
    write_sections(tmp_path, project="演示", destination="发布 v1",
                   route="- [ ] 实现核心")
    d = build_brief(tmp_path, conv)
    assert d["available"] is True
    assert d["source_session"] == "conversation-1.jsonl"
    assert d["rounds"] == 2
    brief = d["brief"]
    assert "[新会话承接简报]" in brief and "conversation-1.jsonl" in brief
    assert "第1轮" in brief and "先做一个发布工具" in brief
    assert "artifacts/a.md" in brief              # 产物汇总（去重）
    arts_section = brief.split("## 产物清单")[1].split("##")[0]
    assert arts_section.count("artifacts/a.md") == 1     # 清单内去重
    assert arts_section.count("artifacts/b.md") == 1
    assert "## 工作区地图摘要" in brief and "发布 v1" in brief
    assert "继续指令" in brief


def test_brief_missing_and_truncation(tmp_path):
    from wuxing.conversation import ConversationState
    from wuxing.handoff import build_brief
    d = build_brief(tmp_path, tmp_path / "nope.jsonl")
    assert d == {"available": False, "source_session": "nope.jsonl",
                 "rounds": 0, "brief": ""}
    conv = tmp_path / ".wuxing" / "c2.jsonl"
    st = ConversationState(conv)
    for i in range(1, 9):
        st.append_turn(i, f"第{i}轮任务" + "长" * 200, [], "完成")
    d2 = build_brief(tmp_path, conv, max_rounds=3, max_chars=400)
    assert "第6轮" in d2["brief"] and "第5轮" not in d2["brief"]  # 只保留最近 3 轮
    assert len(d2["brief"]) <= 400 + 40 and "截断" in d2["brief"]


def test_brief_last_round_status_follows_current_task_state(tmp_path):
    """真测观察（承载简报偏旧）：最后一轮 pending → 确认/续跑完成后显示当前状态。

    现场：轮次记录写于 run 返回时（pending）；确认续跑不改会话轮次 →
    简报末轮一直显示 pending（实际已 done）。展示层以 task_state.json
    当前状态覆盖「最后一轮且原记录 pending」的显示。
    """
    from wuxing.conversation import ConversationState
    from wuxing.handoff import build_brief
    from wuxing.state import TaskState, save_state

    conv = tmp_path / ".wuxing" / "conversation-s.jsonl"
    st = ConversationState(conv)
    st.append_turn(1, "复跑失败票", ["F-T4-v-verdict.md"],
                   "pending；交付物 F-T4-v-verdict.md")
    save_state(TaskState(task_text="复跑失败票", fragments=[], units=[],
                         status="done"), tmp_path / "task_state.json")
    d = build_brief(tmp_path, conv)
    assert "（done；交付物 F-T4-v-verdict.md）" in d["brief"]
    assert "（pending" not in d["brief"]


def test_brief_history_round_status_untouched(tmp_path):
    """历史轮不覆盖（仅最后一轮可能被确认续跑更新）；无 task_state 不造假。"""
    from wuxing.conversation import ConversationState
    from wuxing.handoff import build_brief
    from wuxing.state import TaskState, save_state

    conv = tmp_path / ".wuxing" / "conversation-h.jsonl"
    st = ConversationState(conv)
    st.append_turn(1, "第一轮", [], "pending")
    st.append_turn(2, "第二轮", [], "pending")
    save_state(TaskState(task_text="第二轮", fragments=[], units=[],
                         status="done"), tmp_path / "task_state.json")
    d = build_brief(tmp_path, conv)
    assert "第1轮：第一轮（pending）" in d["brief"]   # 历史轮保持原样
    assert "第2轮：第二轮（done）" in d["brief"]
