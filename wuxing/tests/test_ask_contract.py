"""E2-5（A10）：提问工具契约面（事件/DTO/协议对拍）。

规则：新增引擎事件必须入 `ENGINE_EVENT_TYPE_MAP`（否则协议生成覆盖测试红）；
快照/运行记录须携带 `pending_answers`（REST 对拍——壳刷新后可重建问题卡）。
"""
import dataclasses

from wuxing.events import QuestionAnswered, UnitNeedsAnswer
from wuxing.shell.web import contracts


def test_needs_answer_event_fields():
    e = UnitNeedsAnswer(unit_id="U-1", domain_id="execute",
                        question_id="ask-U-1-1",
                        questions=[{"title": "范围？", "options": ["A", "B"],
                                    "multi": False}])
    assert e.question_id == "ask-U-1-1"
    assert e.questions[0]["title"] == "范围？"
    assert e.reason == ""


def test_question_answered_event_fields():
    e = QuestionAnswered(unit_id="U-1", question_id="ask-U-1-1",
                         answer="A", source="option")
    assert e.question_id == "ask-U-1-1"
    assert e.answer == "A" and e.source == "option"


def test_events_in_type_map():
    assert contracts.ENGINE_EVENT_TYPE_MAP["UnitNeedsAnswer"] == "unit_needs_answer"
    assert contracts.ENGINE_EVENT_TYPE_MAP["QuestionAnswered"] == "question_answered"


def test_question_dtos_registered():
    assert "AskQuestionDto" in contracts.REST_DTOS
    assert "QuestionListDto" in contracts.REST_DTOS
    q = contracts.AskQuestionDto(title="范围？", options=["A", "B"])
    assert q.multi is False
    ql = contracts.QuestionListDto(unit_id="U-1", domain_id="execute",
                                   question_id="ask-U-1-1", questions=[q])
    assert ql.questions[0].title == "范围？"


def test_run_and_snapshot_carry_pending_answers():
    run_fields = {f.name for f in dataclasses.fields(contracts.RunDto)}
    snap_fields = {f.name for f in dataclasses.fields(contracts.SnapshotDto)}
    assert "pending_answers" in run_fields
    assert "pending_answers" in snap_fields


def test_ask_description_plain_language_guidance():
    """重大优化清单 #2：提问工具描述含通俗与语言跟随软约束。"""
    from wuxing.tools.ask_tool import AskUserTool
    d = AskUserTool().description()
    assert "说清" in d, "须要求把「要决定什么 + 选项结果」说清楚"
    assert "界面语言" in d, "须要求语言跟随用户界面"
    assert "看不懂" in d or "能看懂" in d, "须要求通俗（用户能看懂）"
