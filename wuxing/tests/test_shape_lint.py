"""TDD（P1-2）：拆分 lint——机械校验 + 防御性处置（用户裁决 Q1=B/Q2=A/Q3=A）。"""


def _f(fid, domain, text="", deps=None, deliverables=None, forced=False):
    f = {"fragment_id": fid, "domain": domain, "text": text,
         "deps": list(deps or []), "deliverables": list(deliverables or [])}
    if forced:
        f["_forced"] = True
    return f


def test_reroute_verify_when_no_execute():
    """REAL-17：全程无 execute → verify 全转 execute（防御性重路由）。"""
    from wuxing.shape_lint import apply_shape_lint
    frags = [
        _f("F-plan0", "plan", "规划", forced=True),
        _f("F-1", "verify", "验证 hello.txt 内容为 hello", deps=["F-plan0"]),
        _f("F-2", "verify", "核对产物", deps=["F-plan0"]),
    ]
    out, findings, note = apply_shape_lint(frags)
    assert [f["domain"] for f in out] == ["plan", "execute", "execute"]
    assert findings["reroute_ids"] == ["F-1", "F-2"]
    assert findings["no_execute"] is True
    assert "[拆分质量]" in note and "重路由" in note
    # 修复只改域，不动其它字段（文本/依赖/交付物保持）
    assert out[1]["deps"] == ["F-plan0"] and out[1]["text"] == "验证 hello.txt 内容为 hello"


def test_execute_present_no_reroute():
    """有 execute 时不得动 verify 域（不误伤真验证）。"""
    from wuxing.shape_lint import apply_shape_lint
    frags = [
        _f("F-plan0", "plan", "规划", forced=True),
        _f("F-1", "execute", "实现主功能", deps=["F-plan0"]),
        _f("F-2", "verify", "验证主功能", deps=["F-1"]),
    ]
    out, findings, note = apply_shape_lint(frags)
    assert [f["domain"] for f in out] == ["plan", "execute", "verify"]
    assert findings["reroute_ids"] == []
    assert note == ""


def test_dangling_deps_stripped():
    """悬空依赖（不存在/自身）→ 机械剥离（防必然死锁失败）。"""
    from wuxing.shape_lint import apply_shape_lint
    frags = [
        _f("F-plan0", "plan", "规划", forced=True),
        _f("F-1", "execute", "实现", deps=["F-plan0", "F-9", "F-1"]),
    ]
    out, findings, note = apply_shape_lint(frags)
    assert out[1]["deps"] == ["F-plan0"]
    assert findings["dangling"] == {"F-1": ["F-9", "F-1"]}
    assert "依赖剥离" in note


def test_deliverable_overlap_serialized():
    """E3-1/R1：交付物重叠 → 自动串行依赖边（后写者依赖先写者——防并行并写覆盖）。"""
    from wuxing.shape_lint import apply_shape_lint
    frags = [
        _f("F-plan0", "plan", "规划", forced=True),
        _f("F-1", "execute", "写 ledger 第一部分", deps=["F-plan0"],
           deliverables=["ledger.py"]),
        _f("F-2", "execute", "写 ledger 第二部分", deps=["F-plan0"],
           deliverables=["ledger.py"]),
    ]
    out, findings, note = apply_shape_lint(frags)
    assert findings["deliverable_overlaps"] == [
        {"a": "F-1", "b": "F-2", "item": "ledger.py"}]
    assert out[2]["deps"] == ["F-plan0", "F-1"]      # 串行边注入（保序追加）
    assert findings["overlap_serialized"] == [
        {"a": "F-1", "b": "F-2", "item": "ledger.py"}]
    assert [f["fragment_id"] for f in out] == ["F-plan0", "F-1", "F-2"]  # 不改序
    assert "重叠" in note and "串行" in note and "ledger.py" in note


def test_overlap_chain_total_order():
    """E3-1/R1：同一交付物三节点 → 链式串行（F-2←F-1、F-3←F-2——无残留并行对）。"""
    from wuxing.shape_lint import apply_shape_lint
    frags = [
        _f("F-plan0", "plan", "规划", forced=True),
        _f("F-1", "execute", "第一段", deps=["F-plan0"],
           deliverables=["ledger.py"]),
        _f("F-2", "execute", "第二段", deps=["F-plan0"],
           deliverables=["ledger.py"]),
        _f("F-3", "execute", "第三段", deps=["F-plan0"],
           deliverables=["ledger.py"]),
    ]
    out, findings, _note = apply_shape_lint(frags)
    by = {f["fragment_id"]: f for f in out}
    assert by["F-2"]["deps"] == ["F-plan0", "F-1"]
    assert by["F-3"]["deps"] == ["F-plan0", "F-2"]
    assert len(findings["overlap_serialized"]) == 2


def test_overlap_already_ordered_zero_behavior():
    """E3-1/R1：重叠对已存在串行依赖（F-2 已依赖 F-1）→ 零行为（不重复加边/不注记）。"""
    from wuxing.shape_lint import apply_shape_lint
    frags = [
        _f("F-plan0", "plan", "规划", forced=True),
        _f("F-1", "execute", "第一段", deps=["F-plan0"],
           deliverables=["ledger.py"]),
        _f("F-2", "execute", "第二段", deps=["F-plan0", "F-1"],
           deliverables=["ledger.py"]),
    ]
    out, findings, note = apply_shape_lint(frags)
    assert out[2]["deps"] == ["F-plan0", "F-1"]      # 不重复
    assert findings["overlap_serialized"] == []
    assert note == ""


def test_overlap_cycle_safe_skip():
    """E3-1/R1：反向依赖已在（F-1 依赖 F-2）→ 加边成环 → 跳过并注记（环安全）。"""
    from wuxing.shape_lint import apply_shape_lint
    frags = [
        _f("F-plan0", "plan", "规划", forced=True),
        _f("F-1", "execute", "第一段", deps=["F-2"],
           deliverables=["ledger.py"]),
        _f("F-2", "execute", "第二段", deps=[],
           deliverables=["ledger.py"]),
    ]
    out, findings, note = apply_shape_lint(frags)
    by = {f["fragment_id"]: f for f in out}
    assert by["F-2"]["deps"] == []                   # 不加边（防成环）
    assert findings["overlap_serialized"] == []
    assert "重叠" in note and "环" in note


def test_weak_connectivity_note_only():
    """弱连通分量 >1 → 仅注记（信息性）。"""
    from wuxing.shape_lint import apply_shape_lint
    frags = [
        _f("F-plan0", "plan", "规划", forced=True),
        _f("F-1", "execute", "实现 A", deps=["F-plan0"]),
        _f("F-2", "execute", "实现 B"),
    ]
    out, findings, note = apply_shape_lint(frags)
    assert findings["components"] == 2
    assert "连通" in note
    assert [f["fragment_id"] for f in out] == ["F-plan0", "F-1", "F-2"]


def test_forced_scaffold_not_counted_as_component():
    """引擎强制 plan：星形/孤立均不噪声（forced 只作连接器）。"""
    from wuxing.shape_lint import apply_shape_lint
    # 星形：模型节点均挂 forced plan → 1 分量（无注记）
    star = [
        _f("F-plan0", "plan", "规划", forced=True),
        _f("F-1", "execute", "实现 A", deps=["F-plan0"]),
        _f("F-2", "execute", "实现 B", deps=["F-plan0"]),
    ]
    _, findings, note = apply_shape_lint(star)
    assert findings["components"] == 1
    assert note == ""
    # 孤立 forced：forced plan + 单一孤立模型节点 → 1 分量（无注记）
    lone = [
        _f("F-plan0", "plan", "规划", forced=True),
        _f("F-1", "execute", "实现", deps=[]),
    ]
    _, findings2, note2 = apply_shape_lint(lone)
    assert findings2["components"] == 1
    assert note2 == ""


def test_clean_split_zero_behavior():
    """干净拆分：零行为（无注记/无动作）；lint 只读。"""
    from wuxing.shape_lint import apply_shape_lint, lint_fragments
    frags = [
        _f("F-plan0", "plan", "规划", forced=True),
        _f("F-1", "execute", "实现主功能", deps=["F-plan0"],
           deliverables=["main.py"]),
        _f("F-2", "verify", "验证主功能", deps=["F-1"]),
    ]
    out, findings, note = apply_shape_lint(frags)
    assert note == ""
    assert findings["reroute_ids"] == [] and findings["dangling"] == {}
    assert findings["deliverable_overlaps"] == []
    assert findings["overlap_serialized"] == []
    before = [dict(f) for f in frags]
    lint_fragments(frags)
    assert frags == before            # lint 只读（不修改入参）
    assert [f["fragment_id"] for f in out] == ["F-plan0", "F-1", "F-2"]


def test_engine_shape_lint_trace_and_note(tmp_path, monkeypatch):
    """引擎集成（REAL-17）：无 execute 拆分 → 重路由 + trace shape_lint + 报告注记。"""
    import json
    import pathlib

    from wuxing.config import EngineConfig
    from wuxing.engine import Engine

    def fake_segment(self, dag, shape, gr_llm, task_text):
        return [{"fragment_id": "F-1", "domain": "verify", "deps": [],
                 "text": "验证 hello.txt", "deliverables": []}]

    monkeypatch.setattr(Engine, "_segment_to_frags", fake_segment)
    eng = Engine(workdir=pathlib.Path(tmp_path),
                 cfg=EngineConfig(use_real_shape=False))
    frags = eng._build_fragments("创建 hello.txt 并写入 hello")
    # _ensure_plan 插 plan；lint 将 verify 转 execute
    assert [f["domain"] for f in frags] == ["plan", "execute"]
    rows = [json.loads(line) for line in
            (pathlib.Path(tmp_path) / ".wuxing" / "trace.jsonl")
            .read_text(encoding="utf-8").splitlines() if line.strip()]
    lint = [r for r in rows if r.get("event") == "shape_lint"]
    assert lint, "应有 shape_lint trace"
    assert "F-1" in str(lint[-1].get("rerouted"))
    assert "重路由" in eng._shape_quality_note
    assert [r for r in rows if r.get("event") == "shape_quality"]  # 修复后度量仍发


# ---------------- E0-2/A1：verify 锚定（无执行上游 → 防前置否决） ----------------

def test_unanchored_verify_gets_execute_deps():
    """A1：无依赖 verify（决策型）→ 锚定到全部 execute（matrix-multiply 假阴机制修复）。"""
    from wuxing.shape_lint import apply_shape_lint
    frags = [
        _f("F-plan0", "plan", "规划", forced=True),
        _f("F-1", "execute", "实现接口", deps=["F-plan0"]),
        _f("F-2", "verify", "确定接口签名/异常/覆盖约定", deps=[]),
    ]
    out, findings, note = apply_shape_lint(frags)
    assert out[2]["deps"] == ["F-1"]
    assert findings["verify_anchored"] == {"F-2": ["F-1"]}
    assert "锚定" in note and "防前置否决" in note
    assert out[2]["domain"] == "verify"  # 域不动（只加依赖）


def test_unanchored_verify_plan_only_dep_gets_anchored():
    """A1：verify 仅依赖 plan（无执行上游）→ 同样锚定（保序追加）。"""
    from wuxing.shape_lint import apply_shape_lint
    frags = [
        _f("F-plan0", "plan", "规划"),
        _f("F-1", "execute", "实现 A", deps=["F-plan0"]),
        _f("F-2", "execute", "实现 B", deps=["F-plan0"]),
        _f("F-3", "verify", "核对约定", deps=["F-plan0"]),
    ]
    out, findings, note = apply_shape_lint(frags)
    assert out[3]["deps"] == ["F-plan0", "F-1", "F-2"]  # 原依赖保序 + 追加
    assert findings["verify_anchored"] == {"F-3": ["F-1", "F-2"]}
    assert "锚定" in note


def test_anchored_verify_zero_behavior():
    """A1：已有执行上游的 verify → 零行为（不误伤真验证）。"""
    from wuxing.shape_lint import apply_shape_lint
    frags = [
        _f("F-plan0", "plan", "规划", forced=True),
        _f("F-1", "execute", "实现", deps=["F-plan0"]),
        _f("F-2", "verify", "验证", deps=["F-1"]),
    ]
    out, findings, note = apply_shape_lint(frags)
    assert out[2]["deps"] == ["F-1"]
    assert findings["verify_anchored"] == {}
    assert note == ""


def test_anchor_cycle_safe_when_execute_depends_on_verify():
    """A1：环安全——execute 依赖该 verify 时不得锚定（防成环）。"""
    from wuxing.shape_lint import apply_shape_lint
    frags = [
        _f("F-1", "execute", "实现", deps=["F-2"]),
        _f("F-2", "verify", "前置约定核对", deps=[]),
    ]
    out, findings, note = apply_shape_lint(frags)
    assert out[1]["deps"] == []          # 锚定候选仅 F-1 且其依赖 F-2 → 排除
    assert findings["verify_anchored"] == {}
    assert "锚定跳过" in note


def test_engine_verify_anchoring_trace_and_note(tmp_path, monkeypatch):
    """引擎集成（A1）：无执行上游的 verify → 锚定 + trace shape_lint + 报告注记。"""
    import json
    import pathlib

    from wuxing.config import EngineConfig
    from wuxing.engine import Engine

    def fake_segment(self, dag, shape, gr_llm, task_text):
        return [
            {"fragment_id": "F-1", "domain": "execute", "deps": [],
             "text": "实现 matrix.py", "deliverables": ["matrix.py"]},
            {"fragment_id": "F-2", "domain": "verify", "deps": [],
             "text": "验证 matrix.py 的接口签名/异常/覆盖约定", "deliverables": []},
        ]

    monkeypatch.setattr(Engine, "_segment_to_frags", fake_segment)
    eng = Engine(workdir=pathlib.Path(tmp_path),
                 cfg=EngineConfig(use_real_shape=False))
    frags = eng._build_fragments("实现 matrix.py 并确定接口约定")
    by_id = {f["fragment_id"]: f for f in frags}
    assert by_id["F-2"]["deps"] == ["F-1"]
    rows = [json.loads(line) for line in
            (pathlib.Path(tmp_path) / ".wuxing" / "trace.jsonl")
            .read_text(encoding="utf-8").splitlines() if line.strip()]
    lint = [r for r in rows if r.get("event") == "shape_lint"]
    assert lint, "应有 shape_lint trace"
    assert lint[-1].get("verify_anchored") == 1
    assert "锚定" in eng._shape_quality_note
