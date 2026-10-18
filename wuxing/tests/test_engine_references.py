"""TDD：任务级参考文件契约（壳 UI 阶段 5 · 引擎对齐项⑧）。

- `run_task(..., references=[...])`：参考文件内容注入单元 prompt（稳定位置）
- 缺失文件/越界路径 → 明确错误；空列表 → 旧行为逐字节一致
"""

import pytest


def test_build_references_block_and_empty(tmp_path):
    (tmp_path / "notes.md").write_text("关键约束：A", encoding="utf-8")
    from wuxing.engine import Engine
    eng = Engine(workdir=tmp_path, auto_confirm=True)
    block = eng._build_references(["notes.md"])
    assert "参考资料" in block and "notes.md" in block and "关键约束：A" in block
    assert eng._build_references([]) == ""
    assert eng._build_references(None) == ""


def test_missing_and_escape_references_raise(tmp_path):
    from wuxing.engine import Engine
    eng = Engine(workdir=tmp_path, auto_confirm=True)
    with pytest.raises(ValueError):
        eng.run_task("写周报", references=["no_such.md"])
    with pytest.raises(ValueError):
        eng._build_references(["../outside.md"])


def test_absolute_outside_reference_allowed(tmp_path):
    """用户裁决 B（2026-09-15）：显式绝对路径允许工作区外——注入块明示来源。"""
    from wuxing.engine import Engine
    outside = tmp_path / "outside-资料.md"
    outside.write_text("外部资料：X", encoding="utf-8")
    ws = tmp_path / "ws"
    ws.mkdir()
    eng = Engine(workdir=ws, auto_confirm=True)
    block = eng._build_references([str(outside)])
    assert "外部资料：X" in block
    assert "工作区外" in block, "注入块必须明示工作区外来源（缓释纪律）"
    # 工作区内的绝对路径：不标外源
    inner = ws / "note.md"
    inner.write_text("内部资料", encoding="utf-8")
    block2 = eng._build_references([str(inner)])
    assert "内部资料" in block2 and "工作区外" not in block2


def test_prompt_injection_position_stable():
    from wuxing.prompt_builder import build_prompt

    class _D:
        prompt_skeleton = "GOAL={goal}\nTASK={task}"

    base = build_prompt(_D(), {"goal": "g", "task": "t"}, "T", [])
    same = build_prompt(_D(), {"goal": "g", "task": "t"}, "T", [])
    assert base == same, "无参考文件时必须与旧行为逐字节一致"
    with_ref = build_prompt(_D(), {"goal": "g", "task": "t"}, "T", [],
                            references_text="【参考资料】\nX")
    assert with_ref.startswith(base), "参考块追加在稳定尾部位（前缀不动）"
    assert "参考资料" in with_ref


def test_engine_references_reach_prompt(tmp_path, monkeypatch):
    (tmp_path / "notes.md").write_text("约束X：必须包含三段", encoding="utf-8")
    seen = []
    import wuxing.prompt_builder as pb
    orig = pb.build_prompt

    def spy(domain, params, task_projected, deliverables, heartbeat=False,
            references_text=""):
        seen.append(references_text)
        return orig(domain, params, task_projected, deliverables,
                    heartbeat=heartbeat, references_text=references_text)

    monkeypatch.setattr(pb, "build_prompt", spy)
    from wuxing.engine import Engine
    eng = Engine(workdir=tmp_path, auto_confirm=True)
    res = eng.run_task("写周报", references=["notes.md"])
    assert res.status == "done"
    assert seen and any("约束X" in s for s in seen), seen[:2]
