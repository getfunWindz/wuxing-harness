"""TDD（双模式批 3 · Task 1）：设计态——读写/容错/解析/阶段推断/brief。"""


def test_save_load_roundtrip_and_corrupt(tmp_path):
    from wuxing.design_state import load, save, state_path
    assert load(tmp_path) == {}
    row = save(tmp_path, {"session": "c1.jsonl", "phase": "recon", "round": 1,
                          "questions": [{"q": "目标？", "recommend": "A"}],
                          "facts": ["工作区仅 docs/"]})
    assert row["version"] == 1 and row["updated_at"] > 0
    got = load(tmp_path)
    assert got["phase"] == "recon" and got["round"] == 1
    assert got["questions"][0]["q"] == "目标？"
    # 合并语义（patch 只覆盖给定键）
    save(tmp_path, {"round": 2})
    got2 = load(tmp_path)
    assert got2["round"] == 2 and got2["phase"] == "recon"
    # 损坏容错
    state_path(tmp_path).write_text("{broken", encoding="utf-8")
    assert load(tmp_path) == {}


def test_parse_questions_and_facts():
    from wuxing.design_state import parse_facts, parse_questions
    reply = ("已侦察工作区。\n【事实】\n- 仅 docs/ 目录\n- 无测试框架\n"
             "【问题】\n1. 目标平台是什么？（推荐：Windows 桌面）\n"
             "2. 是否需要离线？(推荐: 需要)\n3. 截止时间？\n")
    qs = parse_questions(reply)
    assert [q["q"] for q in qs] == ["目标平台是什么？", "是否需要离线？", "截止时间？"]
    assert qs[0]["recommend"] == "Windows 桌面"
    assert qs[1]["recommend"] == "需要"
    assert qs[2]["recommend"] == ""
    assert parse_facts(reply) == ["仅 docs/ 目录", "无测试框架"]
    # 无块 → 空（不造假）
    assert parse_questions("普通回复") == []
    assert parse_facts("普通回复") == []


def test_infer_phase(tmp_path):
    from wuxing.design_state import infer_phase
    from wuxing.map_doc import write_sections
    # 无地图/无轮次 → recon（推断态）
    phase, inferred = infer_phase(tmp_path, session="c1.jsonl", turns=0)
    assert (phase, inferred) == ("recon", True)
    # 有轮次 → grilling
    assert infer_phase(tmp_path, session="c1.jsonl", turns=2)[0] == "grilling"
    # 地图可用 → map
    write_sections(tmp_path, destination="发布 v1", route="- [ ] 实现核心")
    assert infer_phase(tmp_path, session="c1.jsonl", turns=0)[0] == "map"


def test_brief_contains_state_and_map_pointer(tmp_path):
    from wuxing.design_state import brief, save
    from wuxing.map_doc import write_sections
    save(tmp_path, {"session": "c1.jsonl", "phase": "grilling", "round": 2,
                    "questions": [{"q": "范围？", "recommend": "最小可用"}],
                    "facts": ["仅 docs/"]})
    text = brief(tmp_path)
    assert "grilling" in text and "范围？" in text and "仅 docs/" in text
    assert "WUXING.md" in text            # 地图指针（即使不存在也给出路径语义）
    write_sections(tmp_path, destination="目标X", route="- [ ] A")
    text2 = brief(tmp_path)
    assert "目标X" in text2 or "地图已就绪" in text2


def test_parse_questions_with_blocked_by():
    from wuxing.design_state import parse_questions
    reply = ("【问题】\n1. 部署方式？（推荐：容器）（依赖：Q-1）\n"
             "2. 截止时间？\n")
    qs = parse_questions(reply)
    assert qs[0]["blocked_by"] == ["Q-1"]
    assert qs[1]["blocked_by"] == []


def test_parse_decisions_block():
    from wuxing.design_state import parse_decisions
    reply = ("【决策】\n- Q-2：采用容器部署｜理由：环境一致\n"
             "- 直接上云｜理由：省事｜回滚：D-1\n普通文本")
    ds = parse_decisions(reply)
    assert ds[0] == {"ticket": "Q-2", "text": "采用容器部署",
                     "why": "环境一致", "rollback": ""}
    assert ds[1]["ticket"] == "" and ds[1]["rollback"] == "D-1"


def test_tickets_helpers_and_frontier(tmp_path):
    from wuxing.design_state import frontier_ids, load, save, tickets
    save(tmp_path, {"decision_tickets": [
        {"id": "Q-1", "statement": "A", "blocked_by": [], "status": "open"},
        {"id": "Q-2", "statement": "B", "blocked_by": ["Q-1"], "status": "open"},
        {"id": "Q-3", "statement": "C", "blocked_by": ["Q-9"], "status": "open"},
    ]})
    st = load(tmp_path)
    assert [t["id"] for t in tickets(st)] == ["Q-1", "Q-2", "Q-3"]
    assert frontier_ids(st) == {"Q-1", "Q-3"}   # Q-2 被 open 的 Q-1 阻塞


def test_brief_renders_tickets_with_ids(tmp_path):
    from wuxing.design_state import brief, save
    save(tmp_path, {"phase": "grilling", "round": 2, "branch_head": "D-2",
                    "decision_tickets": [
                        {"id": "Q-1", "statement": "范围？", "recommend": "最小",
                         "blocked_by": [], "status": "open"}]})
    text = brief(tmp_path)
    assert "Q-1" in text and "范围？" in text and "现行决策头：D-2" in text


def test_parse_tickets_block():
    from wuxing.design_state import parse_tickets
    reply = ("【票据】\n- 切片一｜目标：做 A｜验收：A 可用；A 有测试｜依赖：—\n"
             "- 切片二｜目标：做 B｜验收：B 可用｜依赖：T-1\n")
    ts = parse_tickets(reply)
    assert ts[0] == {"title": "切片一", "goal": "做 A",
                     "acceptance": ["A 可用", "A 有测试"], "deps": []}
    assert ts[1]["deps"] == ["T-1"]


def test_brief_hints_tickets_after_spec(tmp_path):
    from wuxing.design_state import brief, save
    save(tmp_path, {"spec_slug": "spec-1",
                    "spec_path": ".wuxing/specs/spec-1.md",
                    "decision_tickets": []})
    text = brief(tmp_path)
    assert "【票据】" in text or "实施票据" in text


def test_brief_hints_spec_after_tickets_closed(tmp_path):
    from wuxing.design_state import brief, save
    from wuxing.map_doc import write_sections
    write_sections(tmp_path, destination="目标X", route="- [ ] A")
    save(tmp_path, {"phase": "map", "round": 2, "decision_tickets": [],
                    "branch_head": "D-1"})
    text = brief(tmp_path)
    assert "write_spec" in text
    save(tmp_path, {"spec_slug": "spec-1",
                    "spec_path": ".wuxing/specs/spec-1.md"})
    text2 = brief(tmp_path)
    assert "规格已生成" in text2 and "spec-1" in text2


def test_brief_renders_drift_hint(tmp_path):
    """C5：设计态含 drift → brief 注入机械校验提示；无 drift 不出现该段。"""
    from wuxing.design_state import brief, save
    save(tmp_path, {"drift": [
        {"round": 2, "kind": "unknown-ticket", "id": "Q-9",
         "detail": "决策引用了未打开票据", "ts": 1.0}]})
    text = brief(tmp_path)
    assert "机械校验" in text and "unknown-ticket" in text and "Q-9" in text
    save(tmp_path, {"drift": []})
    assert "机械校验" not in brief(tmp_path)
