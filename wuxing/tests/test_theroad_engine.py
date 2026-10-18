"""TDD（双模式批 3 · Task 3）：引擎闸 + 设计轮 + write_map + 地图摘要。"""
import pathlib
import typing


class _DesignLlm:
    """按调用序返回预设回复的 stub（原生 tools；记录 messages/tools）。"""
    usage_history: typing.ClassVar[list] = []
    replies: typing.ClassVar[list] = []

    def __init__(self):
        self.messages_seen: list = []
        self.tools_seen: list = []

    def name(self): return "design-stub"

    def spec(self): return "design-stub"

    def supports_native_tools(self): return True

    def chat(self, messages, tools=None):
        self.messages_seen.append([dict(m) for m in messages])
        self.tools_seen.append([t["function"]["name"] for t in (tools or [])])
        self.usage_history.append({"input": 100, "output": 10,
                                   "cache_read": 0, "cache_write": 0})
        from wuxing.llm.tool_results import ToolCallResult
        text = self.replies.pop(0) if self.replies else "完成声明：已完成"
        return ToolCallResult(text=text, tool_calls=[])


def _theroad_engine(tmp_path):
    from wuxing.config import EngineConfig
    from wuxing.engine import Engine
    from wuxing.session_modes import save as save_mode
    save_mode(tmp_path, "conversation-w.jsonl", "theroad", "")
    llm = _DesignLlm()
    eng = Engine(cfg=EngineConfig(use_real_shape=False), workdir=tmp_path,
                 llm=llm, auto_confirm=True)
    return eng, llm


def test_gate_returns_needs_design_and_writes_state(tmp_path):
    eng, llm = _theroad_engine(tmp_path)
    _DesignLlm.replies = [
        ("已完成侦察。\n【事实】\n- 工作区仅 docs/\n"
         "【问题】\n1. 目标平台？（推荐：Windows）\n")]
    from wuxing.conversation import ConversationState
    conv = ConversationState(pathlib.Path(tmp_path) / ".wuxing" / "conversation-w.jsonl")
    events = []
    res = eng.run_task("做一个发布工具", on_event=events.append,
                       conversation=conv)
    assert res.status == "needs_design"
    # 机制：不进入执行管线——task_state 不写（断点恢复数据不被污染）
    assert not (pathlib.Path(tmp_path) / "task_state.json").exists()
    from wuxing.design_state import load
    st = load(tmp_path)
    assert st["round"] == 1 and st["phase"] == "grilling"
    assert st["questions"][0]["q"] == "目标平台？"
    types = [type(e).__name__ for e in events]
    assert "NeedsDesign" in types and "TaskDone" in types
    assert "DesignPhaseChanged" in types
    dp = next(e for e in events if type(e).__name__ == "DesignPhaseChanged")
    assert dp.to_phase == "grilling" and dp.round == 1
    # 设计单元装配：工具面含 write_map；消息含设计态 brief（提示词）
    names = set(llm.tools_seen[0])
    assert "write_map" in names and "bash" in names and "read_file" in names
    joined = "\n".join(str(m.get("content", "")) for m in llm.messages_seen[0])
    assert "循迹设计态" in joined and "WUXING.md" in joined


def test_engine_proposes_tickets_and_gate(tmp_path):
    """spec 就绪 + 【票据】块 → 创建 proposed + 事件；无 ready 票据时仍在设计流。"""
    eng, _llm = _theroad_engine(tmp_path)
    from wuxing import design_state, spec_doc
    from wuxing.map_doc import write_sections
    write_sections(tmp_path, destination="目标 A", route="- [ ] 实现")
    _e = spec_doc.write(tmp_path, title="规格", sections={"problem": "p"})
    design_state.save(tmp_path, {"spec_slug": _e["slug"],
                                 "spec_path": f".wuxing/specs/{_e['slug']}.md"})
    _DesignLlm.replies = ["设计已更新。\n【票据】\n- 切片一｜目标：A｜验收：A 可用\n"]
    from wuxing.conversation import ConversationState
    conv = ConversationState(pathlib.Path(tmp_path) / ".wuxing" / "conversation-w.jsonl")
    events = []
    res = eng.run_task("提票据", on_event=events.append, conversation=conv)
    assert res.status == "needs_design"          # 票据未发布 → 仍设计流
    from wuxing.tickets import load, publish
    assert [t["title"] for t in load(tmp_path)] == ["切片一"]
    assert load(tmp_path)[0]["status"] == "proposed"
    types = [type(e).__name__ for e in events]
    assert "ImplTicketChanged" in types
    # 发布后 → 执行路径（闸放行）
    publish(tmp_path)
    _DesignLlm.replies = ["完成声明：已完成"]
    res2 = eng.run_task("执行", on_event=[].append, conversation=conv)
    assert res2.status != "needs_design"


def test_ticket_writeback_clears_stale_error_on_success(tmp_path):
    """W4.5：复跑成功回写时清理上轮残留 error（防失败信息误导）。"""
    from wuxing import tickets
    from wuxing.protocols import UnitResult
    eng, conv = _ticket_ready_setup(tmp_path)
    tickets.update(tmp_path, "T-1", {"status": "failed",
                                      "error": "F-T1-v:failed(验收不通过)"})
    tickets.update(tmp_path, "T-1", {"status": "ready"})  # 复跑（error 未清）
    eng.orchestrator.run = lambda pending, task_text, **kw: [
        UnitResult(unit_id=f["fragment_id"], domain_id=f["domain"],
                   status="ok") for f in pending]
    res = eng.run_task("交给执行", on_event=[].append, conversation=conv)
    assert res.status == "done"
    t = tickets.find(tmp_path, "T-1")
    assert t["status"] == "done" and t["error"] == ""


def test_ticket_external_done_dep_seeded(tmp_path):
    """W4.5：活跃票 deps 指向非活跃 done 票 → 外部已完成 seed（下游可开工）。

    现场：重置失败票时 deps 指向未激活的 done 票 → 悬空依赖；
    机制按「外部已完成依赖」声明（seed 其 verify 碎片为 ok）。
    """
    from wuxing import design_state, spec_doc, tickets
    from wuxing.map_doc import write_sections
    from wuxing.protocols import UnitResult
    eng, _llm = _theroad_engine(tmp_path)
    write_sections(tmp_path, destination="目标 A", route="- [ ] 实现")
    e = spec_doc.write(tmp_path, title="规格", sections={"problem": "p"})
    design_state.save(tmp_path, {"spec_slug": e["slug"], "spec_path": e["path"]})
    t1 = tickets.create(tmp_path, title="切片一", goal="A", acceptance=["A 可用"])
    t2 = tickets.create(tmp_path, title="切片二", goal="B", deps=[t1["id"]])
    tickets.publish(tmp_path)
    tickets.update(tmp_path, t1["id"], {"status": "done"})   # 非活跃、已完成
    captured = {}

    def fake_run(frags, task_text, **kw):
        captured["frags"] = frags
        captured["seed"] = kw.get("seed_done")
        return [UnitResult(unit_id=f["fragment_id"], domain_id=f["domain"],
                           status="ok") for f in frags]

    eng.orchestrator.run = fake_run
    from wuxing.conversation import ConversationState
    conv = ConversationState(
        pathlib.Path(tmp_path) / ".wuxing" / "conversation-w.jsonl")
    res = eng.run_task("交给执行", on_event=[].append, conversation=conv)
    fids = {f["fragment_id"] for f in captured["frags"]}
    assert fids == {"F-T2", "F-T2-v"}            # 仅活跃票构建 DAG
    seed = captured.get("seed") or {}
    assert seed["F-T1-v"].status == "ok"         # 外部已完成声明（验收通过语义）
    assert "外部已完成依赖" in res.report
    assert tickets.find(tmp_path, t2["id"])["status"] == "done"


def test_ticket_external_undone_dep_reported(tmp_path):
    """W4.5：活跃票 deps 指向非活跃未完成票 → 不 seed，报告悬空注记（指引重置）。"""
    from wuxing import design_state, spec_doc, tickets
    from wuxing.map_doc import write_sections
    from wuxing.protocols import UnitResult
    eng, _llm = _theroad_engine(tmp_path)
    write_sections(tmp_path, destination="目标 A", route="- [ ] 实现")
    e = spec_doc.write(tmp_path, title="规格", sections={"problem": "p"})
    design_state.save(tmp_path, {"spec_slug": e["slug"], "spec_path": e["path"]})
    t1 = tickets.create(tmp_path, title="切片一", goal="A")
    tickets.create(tmp_path, title="切片二", goal="B", deps=[t1["id"]])
    tickets.publish(tmp_path)
    tickets.update(tmp_path, t1["id"], {"status": "failed"})  # 非活跃、未完成
    captured = {}

    def fake_run(frags, task_text, **kw):
        captured["seed"] = kw.get("seed_done")
        return [UnitResult(unit_id=f["fragment_id"], domain_id=f["domain"],
                           status="failed") for f in frags]

    eng.orchestrator.run = fake_run
    from wuxing.conversation import ConversationState
    conv = ConversationState(
        pathlib.Path(tmp_path) / ".wuxing" / "conversation-w.jsonl")
    res = eng.run_task("交给执行", on_event=[].append, conversation=conv)
    assert not (captured.get("seed") or {})     # 未完成依赖不得伪声明
    assert "依赖票据未激活且未完成" in res.report
    assert t1["id"] in res.report               # 指名可追


def test_ticket_run_builds_dag_and_writes_back(tmp_path):
    """theroad + ready 票据 → 不经形状化直建 DAG；执行后回写 + 报告注记。"""
    eng, _llm = _theroad_engine(tmp_path)
    from wuxing import design_state, spec_doc, tickets
    from wuxing.map_doc import write_sections
    write_sections(tmp_path, destination="目标 A", route="- [ ] 实现")
    e = spec_doc.write(tmp_path, title="规格", sections={"problem": "p"})
    design_state.save(tmp_path, {"spec_slug": e["slug"], "spec_path": e["path"]})
    tickets.create(tmp_path, title="切片一", goal="A", acceptance=["A 可用"])
    tickets.publish(tmp_path)
    _DesignLlm.replies = ["完成声明：已完成"] * 6
    from wuxing.conversation import ConversationState
    conv = ConversationState(pathlib.Path(tmp_path) / ".wuxing" / "conversation-w.jsonl")
    res = eng.run_task("交给执行", on_event=[].append, conversation=conv)
    assert "[票据编排]" in res.report
    fids = {f["fragment_id"] for f in res.fragments}
    assert {"F-T1", "F-T1-v"} <= fids
    from wuxing.tickets import load
    t = load(tmp_path)[0]
    assert t["status"] in ("done", "failed")      # 已回写（不再 running/ready）
    assert t["fragment_ids"] == ["F-T1", "F-T1-v"]


def test_map_usable_executes_with_digest(tmp_path):
    eng, _llm = _theroad_engine(tmp_path)
    from wuxing.map_doc import write_sections
    write_sections(tmp_path, destination="发布 v1", route="- [ ] 实现")
    # 批 3/5：设计流收口 = 交接口（phase=ready）或地图+规格+已发布票据；
    # 本用例验证「地图摘要 + 形状化执行」路径——用交接口标记（无活跃票据）
    from wuxing import design_state, spec_doc
    _e = spec_doc.write(tmp_path, title="发布 v1", sections={"problem": "p"})
    design_state.save(tmp_path, {"spec_slug": _e["slug"], "spec_path": _e["path"],
                                 "spec_hash": _e["hash"], "phase": "ready"})
    _DesignLlm.replies = ["完成声明：已完成"]
    captured = {}
    orig = eng._build_fragments

    def _spy(text):
        captured["text"] = text
        return orig(text)

    eng._build_fragments = _spy
    from wuxing.conversation import ConversationState
    conv = ConversationState(pathlib.Path(tmp_path) / ".wuxing" / "conversation-w.jsonl")
    res = eng.run_task("实现核心", conversation=conv)
    assert res.status != "needs_design"          # 已进执行管线
    assert res.fragments
    assert "[工作区地图摘要]" in captured.get("text", "")
    assert "发布 v1" in captured.get("text", "")
    # 形状化前缀不污染会话原文（TaskResult.task_text 保持用户输入）
    assert res.task_text == "实现核心"


def test_spec_written_event_and_brief_hint(tmp_path, monkeypatch):
    """设计轮内 spec 落盘 → SpecWritten（指针变化检测）。"""
    eng, _llm = _theroad_engine(tmp_path)
    _DesignLlm.replies = ["已完成。\n设计已更新。\n"]
    from wuxing.map_doc import write_sections
    write_sections(tmp_path, destination="发布 v1", route="- [ ] 实现")
    from wuxing import design_state, spec_doc

    def fake_run(frags, task, **kw):
        entry = spec_doc.write(tmp_path, title="发布 v1",
                               sections={"problem": "p"})
        design_state.save(tmp_path, {
            "spec_slug": entry["slug"],
            "spec_path": f".wuxing/specs/{entry['slug']}.md",
            "spec_hash": entry["hash"]})
        return []

    monkeypatch.setattr(eng.orchestrator, "run", fake_run)
    from wuxing.conversation import ConversationState
    conv = ConversationState(pathlib.Path(tmp_path) / ".wuxing" / "conversation-w.jsonl")
    events = []
    eng.run_task("合成规格", on_event=events.append, conversation=conv)
    types = [type(e).__name__ for e in events]
    assert "SpecWritten" in types
    sw = next(e for e in events if type(e).__name__ == "SpecWritten")
    assert sw.slug.startswith("spec-") and sw.path.endswith(".md")
    assert len(sw.hash) == 64


def test_write_spec_tool_writes_file_and_state(tmp_path):
    eng, _llm = _theroad_engine(tmp_path)
    tool = eng.tools.get("write_spec")
    assert tool is not None
    r = tool.execute(title="发布工具", slug="demo",
                     problem="现状缺失", solution="新增 CLI",
                     stories="- 导出报告", testing="单测")
    assert r.status == "ok"
    from wuxing.design_state import load
    from wuxing.spec_doc import read, spec_path
    st = load(tmp_path)
    assert st["spec_slug"] == "demo"
    assert st["spec_path"] == ".wuxing/specs/demo.md" and len(st["spec_hash"]) == 64
    assert "## Problem Statement" in read(tmp_path, "demo")
    assert spec_path(tmp_path, "demo").is_file()
    # 非法 slug 可见失败（不静默）
    r2 = tool.execute(title="X", slug="../evil")
    assert r2.status == "error"


def test_write_map_tool_writes_file_and_state(tmp_path):
    eng, _llm = _theroad_engine(tmp_path)
    tool = eng.tools.get("write_map")
    assert tool is not None
    r = tool.execute(destination="目标 A", route="- [ ] 步骤一",
                     decisions="2026-09-24 · 选择 A · 简单 · 会话",
                     fog="", out_of_scope="", project="演示")
    assert r.status == "ok"
    from wuxing.map_doc import map_path, parse
    text = map_path(tmp_path).read_text(encoding="utf-8")
    assert "目标 A" in text and parse(text)["project"] == "演示"
    from wuxing.design_state import load
    st = load(tmp_path)
    assert st["phase"] == "map" and len(st.get("map_hash") or "") == 64


def test_headless_theroad_not_blocked(tmp_path):
    """headless（无会话）选循迹：不拦截执行（设计 §8）。"""
    from wuxing.config import EngineConfig
    from wuxing.engine import Engine
    llm = _DesignLlm()
    eng = Engine(cfg=EngineConfig(use_real_shape=False,
                                  mode_default="theroad"),
                 workdir=tmp_path, llm=llm, auto_confirm=True)
    _DesignLlm.replies = ["完成声明：已完成"]
    res = eng.run_task("直跑小任务")
    assert res.status != "needs_design"
    assert res.fragments
    assert "循迹" in res.report or "headless" in res.report


def test_map_written_event_on_change(tmp_path, monkeypatch):
    """设计轮内地图文件变化 → MapWritten（哈希事件；不依赖工具调用路径）。"""
    eng, _llm = _theroad_engine(tmp_path)
    _DesignLlm.replies = ["已完成侦察。\n【事实】\n- 工作区\n"]
    from wuxing.map_doc import map_path

    def fake_run(frags, task, **kw):
        map_path(tmp_path).write_text(
            "# 演示 · WUXING 地图\n\n## 目的地\n\n发布 v1\n", encoding="utf-8")
        return []

    monkeypatch.setattr(eng.orchestrator, "run", fake_run)
    from wuxing.conversation import ConversationState
    conv = ConversationState(pathlib.Path(tmp_path) / ".wuxing" / "conversation-w.jsonl")
    events = []
    res = eng.run_task("目标", on_event=events.append, conversation=conv)
    types = [type(e).__name__ for e in events]
    assert "MapWritten" in types and "DesignPhaseChanged" in types
    mw = next(e for e in events if type(e).__name__ == "MapWritten")
    assert mw.path == "WUXING.md" and len(mw.hash) == 64
    assert res.status == "needs_design"   # 批 1 不改闸语义（override 见 Task 4）


def test_override_bypasses_gate(tmp_path):
    """显式 override：无地图也执行（报告注记；不再走设计轮）。"""
    eng, _llm = _theroad_engine(tmp_path)
    _DesignLlm.replies = ["完成声明：已完成"]
    from wuxing.conversation import ConversationState
    conv = ConversationState(pathlib.Path(tmp_path) / ".wuxing" / "conversation-w.jsonl")
    res = eng.run_task("直跑任务", conversation=conv, overrides={"no_map"})
    assert res.status != "needs_design"
    assert "[循迹 override]" in res.report
    assert (tmp_path / "task_state.json").exists()  # 执行路径已走


def test_ticket_created_then_closed_into_map(tmp_path):
    """票据生命周期：问题→Q-1；回答→决策入地图（D-1）+ 票据即弃 + 事件。"""
    eng, _llm = _theroad_engine(tmp_path)
    from wuxing.conversation import ConversationState
    from wuxing.map_doc import parse_decisions, read
    conv = ConversationState(pathlib.Path(tmp_path) / ".wuxing" / "conversation-w.jsonl")
    _DesignLlm.replies = ["已完成侦察。\n【问题】\n1. 部署方式？（推荐：容器）\n"]
    ev1 = []
    eng.run_task("做一个工具", on_event=ev1.append, conversation=conv)
    from wuxing.design_state import load
    st = load(tmp_path)
    assert [t["id"] for t in st["decision_tickets"]] == ["Q-1"]
    assert st["next_ticket"] == 2
    types = [type(e).__name__ for e in ev1]
    assert "DecisionTicketChanged" in types
    # 第二轮回答案 → 【决策】块关闭 Q-1
    _DesignLlm.replies = ["收到。\n【决策】\n- Q-1：采用容器部署｜理由：环境一致\n设计已更新。\n"]
    ev2 = []
    eng.run_task("采用容器", on_event=ev2.append, conversation=conv)
    st2 = load(tmp_path)
    assert st2["decision_tickets"] == []          # 用完即弃
    assert st2["branch_head"] == "D-1"
    ds = parse_decisions((read(tmp_path) or {}).get("decisions") or [])
    assert ds[0]["id"] == "D-1" and ds[0]["text"] == "采用容器部署"
    assert ds[0]["source"] == "Q-1" and ds[0]["why"] == "环境一致"
    types2 = [type(e).__name__ for e in ev2]
    assert "DecisionTicketChanged" in types2 and "MapWritten" in types2


def test_ticket_rollback_decision(tmp_path):
    """回滚：决策带 回滚：D-1 → 上游=D-1、取代=现行头（分岔保留）。"""
    eng, _llm = _theroad_engine(tmp_path)
    from wuxing.conversation import ConversationState
    from wuxing.map_doc import parse_decisions, read
    conv = ConversationState(pathlib.Path(tmp_path) / ".wuxing" / "conversation-w.jsonl")
    _DesignLlm.replies = ["【决策】\n- Q-1：先做 A｜理由：快\n设计已记录。\n"]
    eng.run_task("A", on_event=[].append, conversation=conv)
    _DesignLlm.replies = ["【决策】\n- Q-2：改做 B｜理由：重估｜回滚：D-1\n设计已回滚。\n"]
    eng.run_task("B", on_event=[].append, conversation=conv)
    ds = parse_decisions((read(tmp_path) or {}).get("decisions") or [])
    assert ds[1]["upstream"] == ["D-1"] and ds[1]["supersedes"] == ["D-1"]


def _ticket_ready_setup(tmp_path):
    """票据编排前置：地图 + 规格 + 已发布票据；返回 (eng, conv)。"""
    eng, _llm = _theroad_engine(tmp_path)
    from wuxing import design_state, spec_doc, tickets
    from wuxing.map_doc import write_sections
    write_sections(tmp_path, destination="目标 A", route="- [ ] 实现")
    e = spec_doc.write(tmp_path, title="规格", sections={"problem": "p"})
    design_state.save(tmp_path, {"spec_slug": e["slug"], "spec_path": e["path"]})
    tickets.create(tmp_path, title="切片一", goal="A", acceptance=["A 可用"])
    tickets.publish(tmp_path)
    from wuxing.conversation import ConversationState
    conv = ConversationState(
        pathlib.Path(tmp_path) / ".wuxing" / "conversation-w.jsonl")
    return eng, conv


def test_design_reply_skips_empty_and_tool_logs():
    """真测 REAL-8：设计轮末轮空文本（纯工具轮）不得遮蔽上一轮的正式回复。

    实况：第 4 轮模型已按契约输出【票据】/【决策】+完成声明；第 5 轮空文本
    （纯工具调用）被 logs.append("") 记入——`_design_reply` 逆扫时空串未被过滤
    → 返回 "" → 票据/决策全部丢失（spec 已落盘但 tickets=[]/Q 仍 open）。
    """
    from wuxing.engine import Engine
    from wuxing.protocols import UnitResult

    u = UnitResult(
        unit_id="D-4", domain_id="design", status="failed",
        logs=["[tool] write_spec: 规格已写入 .wuxing/specs/todo-v2-tags-due.md",
              "规格已落盘。\n【票据】\n- 切片一｜目标：A｜验收：B",
              "[guard] blocked: read_file: internal data hidden",
              ""])
    reply = Engine._design_reply([u])
    assert "【票据】" in reply


def test_design_block_not_hijacked_by_prose_mention():
    """真测 REAL-9：完成声明里的「【决策】块」「【票据】块」提及不得劫持块解析。

    实况（D-5）：模型合规输出 3 决策 + 4 票据，但完成声明又提到
    「已按顺序输出【决策】块与【票据】块」——`_block` 的 rfind 取到该提及，
    body 只剩「块（Q-1/Q-2/Q-3 全部关闭）与」→ 解析为空 → 票据/决策全丢。
    """
    from wuxing import design_state

    text = ("【决策】\n- Q-1：采用 A｜理由：稳\n- Q-1/Q-2/Q-3 已按上表关闭并入地图\n\n"
            "【票据】\n- 切片一｜目标：A｜验收：B\n\n"
            "完成声明：本回复已按顺序输出【决策】块与【票据】块。")
    ds = design_state.parse_decisions(text)
    assert [d["ticket"] for d in ds] == ["Q-1"]
    assert [d["text"] for d in ds] == ["采用 A"]
    tk = design_state.parse_tickets(text)
    assert [t["title"] for t in tk] == ["切片一"]


def test_design_block_line_anchored_over_prose_mention():
    """行首锚定：块前引用（如「按下面【问题】块…」）不得抢先。"""
    from wuxing import design_state

    text = "请按下面【问题】块回答：\n【问题】\n1. 目标平台？（推荐：Windows）\n"
    qs = design_state.parse_questions(text)
    assert [q["q"] for q in qs] == ["目标平台？"]


def test_ticket_cancel_keeps_running_then_resume_writes_done(tmp_path):
    """断点恢复（审查 F1）：取消不把票标 failed；resume 完成 → 回写 done + 事件。"""
    from wuxing import tickets
    from wuxing.protocols import UnitResult
    eng, conv = _ticket_ready_setup(tmp_path)

    eng.orchestrator.run = lambda pending, task_text, **kw: [
        UnitResult(unit_id=f["fragment_id"], domain_id=f["domain"],
                   status="cancelled") for f in pending]
    res = eng.run_task("交给执行", on_event=[].append, conversation=conv)
    assert res.status == "cancelled"
    # 非终态：取消是断点而非失败——票保持 running 可续跑
    assert tickets.find(tmp_path, "T-1")["status"] == "running"

    events = []
    eng.orchestrator.run = lambda pending, task_text, **kw: [
        UnitResult(unit_id=f["fragment_id"], domain_id=f["domain"],
                   status="ok") for f in pending]
    res2 = eng.resume_task(on_event=events.append)
    assert res2.status == "done"
    # 旧 cancelled 结果不得参与裁决（同 unit_id 取最新）
    assert tickets.find(tmp_path, "T-1")["status"] == "done"
    changed = [ev for ev in events if type(ev).__name__ == "ImplTicketChanged"]
    assert [(ev.id, ev.status) for ev in changed] == [("T-1", "done")]


def test_ticket_verify_verdict_fail_marks_ticket_failed(tmp_path):
    """验收不通过（verdict_fail）→ 票据 failed（对齐 _task_status 验收语义）。"""
    from wuxing import tickets
    from wuxing.protocols import UnitResult
    eng, conv = _ticket_ready_setup(tmp_path)
    eng.orchestrator.run = lambda pending, task_text, **kw: [
        UnitResult(unit_id=f["fragment_id"], domain_id=f["domain"], status="ok",
                   verdict_fail=(f["domain"] == "verify")) for f in pending]
    res = eng.run_task("交给执行", on_event=[].append, conversation=conv)
    assert res.status == "failed"
    assert tickets.find(tmp_path, "T-1")["status"] == "failed"


def test_ticket_pending_then_confirm_writes_back(tmp_path):
    """挂起确认：need_confirm 期间票保持 running；确认通过后回写 done。"""
    from wuxing import tickets
    from wuxing.protocols import UnitResult
    eng, conv = _ticket_ready_setup(tmp_path)
    eng.orchestrator.run = lambda pending, task_text, **kw: [
        UnitResult(unit_id=f["fragment_id"], domain_id=f["domain"],
                   status="ok" if f["domain"] == "execute"
                   else "needs_confirm") for f in pending]
    eng.run_task("交给执行", on_event=[].append, conversation=conv)
    assert tickets.find(tmp_path, "T-1")["status"] == "running"
    eng.orchestrator.runner.run_unit = (
        lambda unit_id, domain, params, **kw: UnitResult(
            unit_id=unit_id, domain_id=domain, status="ok"))
    res = eng.confirm_unit("F-T1-v", True, on_event=[].append)
    assert res.status == "done"
    assert tickets.find(tmp_path, "T-1")["status"] == "done"


# ---- C5：决策票 open 漂移收口（机械校验/提示） ----

def test_unknown_ticket_closure_records_drift(tmp_path):
    """C5：【决策】关闭未知票据 id → 不误关、决策仍入图、drift 可见（不静默）。"""
    eng, _llm = _theroad_engine(tmp_path)
    from wuxing.conversation import ConversationState
    from wuxing.design_state import load
    from wuxing.map_doc import parse_decisions, read
    conv = ConversationState(pathlib.Path(tmp_path) / ".wuxing" / "conversation-w.jsonl")
    _DesignLlm.replies = ["【问题】\n1. 部署方式？（推荐：容器）\n"]
    eng.run_task("做一个工具", on_event=[].append, conversation=conv)
    _DesignLlm.replies = ["【决策】\n- Q-9：采用容器部署｜理由：环境一致\n设计已更新。\n"]
    eng.run_task("采用容器", on_event=[].append, conversation=conv)
    st = load(tmp_path)
    assert [t["id"] for t in st["decision_tickets"]] == ["Q-1"]   # 未误关
    ds = parse_decisions((read(tmp_path) or {}).get("decisions") or [])
    assert ds[0]["source"] == "Q-9"                                # 决策不丢
    drift = st.get("drift") or []
    assert any(d["kind"] == "unknown-ticket" and d["id"] == "Q-9"
               and d["round"] == 2 for d in drift), drift


def test_duplicate_closure_records_drift(tmp_path):
    """C5：同一轮重复关闭同一票据（第二次起）→ drift（不静默）。"""
    eng, _llm = _theroad_engine(tmp_path)
    from wuxing.conversation import ConversationState
    from wuxing.design_state import load
    conv = ConversationState(pathlib.Path(tmp_path) / ".wuxing" / "conversation-w.jsonl")
    _DesignLlm.replies = ["【问题】\n1. 先做 A？\n"]
    eng.run_task("做一个工具", on_event=[].append, conversation=conv)
    _DesignLlm.replies = ["【决策】\n- Q-1：先做 A｜理由：快\n- Q-1：再记 A｜理由：重复\n设计已记录。\n"]
    eng.run_task("先做 A", on_event=[].append, conversation=conv)
    st = load(tmp_path)
    assert st["decision_tickets"] == []                            # 首条已关闭
    drift = st.get("drift") or []
    assert any(d["kind"] == "unknown-ticket" and d["id"] == "Q-1"
               for d in drift), drift


def test_dangling_blocked_by_records_drift(tmp_path):
    """C5：新票据 blocked_by 引用未知 id → drift（悬挂依赖可见）。"""
    eng, _llm = _theroad_engine(tmp_path)
    from wuxing.conversation import ConversationState
    from wuxing.design_state import load
    conv = ConversationState(pathlib.Path(tmp_path) / ".wuxing" / "conversation-w.jsonl")
    _DesignLlm.replies = ["【问题】\n1. 先定 A？\n2. 再定 B？（依赖：Q-99）\n"]
    eng.run_task("做一个工具", on_event=[].append, conversation=conv)
    st = load(tmp_path)
    assert "Q-99" in st["decision_tickets"][1]["blocked_by"]
    drift = st.get("drift") or []
    assert any(d["kind"] == "dangling-blocked-by" and d["id"] == "Q-99"
               for d in drift), drift


def test_valid_flow_records_no_drift(tmp_path):
    """C5：正常流（创建→关闭）不产生 drift（防误报——回归护栏）。"""
    eng, _llm = _theroad_engine(tmp_path)
    from wuxing.conversation import ConversationState
    from wuxing.design_state import load
    conv = ConversationState(pathlib.Path(tmp_path) / ".wuxing" / "conversation-w.jsonl")
    _DesignLlm.replies = ["【问题】\n1. 部署方式？（推荐：容器）\n"]
    eng.run_task("做一个工具", on_event=[].append, conversation=conv)
    _DesignLlm.replies = ["【决策】\n- Q-1：采用容器部署｜理由：环境一致\n设计已更新。\n"]
    eng.run_task("采用容器", on_event=[].append, conversation=conv)
    st = load(tmp_path)
    assert st["decision_tickets"] == []                   # 正常关闭（防漏测）
    assert not (st.get("drift") or [])


def test_write_spec_warns_on_open_tickets(tmp_path):
    """C5：带未关闭决策票合成规格 → 软提示（警告行 + drift；仍写入）。"""
    eng, _llm = _theroad_engine(tmp_path)
    from wuxing.design_state import load, save
    save(tmp_path, {"decision_tickets": [
        {"id": "Q-1", "statement": "部署方式？", "recommend": "",
         "blocked_by": [], "status": "open", "resolution": "",
         "round": 1, "ts": 1.0}]})
    tool = eng.tools.get("write_spec")
    r = tool.execute(title="发布工具", slug="warn-demo", problem="p")
    assert r.status == "ok"                       # 软口径：不硬拦
    assert "警告" in r.content and "Q-1" in r.content, r.content
    st = load(tmp_path)
    assert any(d["kind"] == "spec-with-open-tickets"
               for d in (st.get("drift") or [])), st.get("drift")


def test_write_spec_clean_when_no_open_tickets(tmp_path):
    """C5：无未关闭票据 → 无警告、无 drift（防误报）。"""
    eng, _llm = _theroad_engine(tmp_path)
    tool = eng.tools.get("write_spec")
    r = tool.execute(title="发布工具", slug="clean-demo", problem="p")
    assert r.status == "ok"
    assert "警告" not in r.content
    from wuxing.design_state import load
    assert not (load(tmp_path).get("drift") or [])
