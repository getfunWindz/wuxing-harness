"""TDD（二期批 4）：实施票据存储/发布/依赖校验。"""


def test_create_load_and_merge(tmp_path):
    from wuxing.tickets import create, load, update
    t1 = create(tmp_path, title="切片一", goal="做 A", acceptance=["A 可用"],
                deps=[], spec="spec-1")
    t2 = create(tmp_path, title="切片二", goal="做 B", deps=[t1["id"]],
                spec="spec-1")
    assert t1["id"] == "T-1" and t2["id"] == "T-2"
    assert t1["status"] == "proposed" and t2["deps"] == ["T-1"]
    got = load(tmp_path)
    assert [t["id"] for t in got] == ["T-1", "T-2"]
    # 更新归并
    update(tmp_path, "T-1", {"status": "ready"})
    assert load(tmp_path)[0]["status"] == "ready"
    # 损坏行跳过（整文件损坏 → 空）
    (tmp_path / ".wuxing" / "tickets.jsonl").write_text("{broken\n",
                                                        encoding="utf-8")
    assert load(tmp_path) == []


def test_to_fragments_maps_tickets_and_deps(tmp_path):
    from wuxing.tickets import create, to_fragments
    t1 = create(tmp_path, title="切片一", goal="A", acceptance=["A 可用"])
    t2 = create(tmp_path, title="切片二", goal="B", acceptance=["B 可用"],
                deps=[t1["id"]])
    frags = to_fragments([t1, t2], spec_text="规格摘要 X")
    by_id = {f["fragment_id"]: f for f in frags}
    assert set(by_id) == {"F-T1", "F-T1-v", "F-T2", "F-T2-v"}
    assert by_id["F-T1"]["domain"] == "execute"
    assert by_id["F-T1-v"]["domain"] == "verify"
    assert by_id["F-T1-v"]["deps"] == ["F-T1"]
    assert by_id["F-T2"]["deps"] == ["F-T1-v"]      # 依赖票验收通过才开工
    assert by_id["F-T2-v"]["deps"] == ["F-T2"]
    assert by_id["F-T1"]["ticket"] == "T-1"
    assert "A 可用" in by_id["F-T1"]["text"]
    assert "规格摘要 X" in by_id["F-T1"]["text"]


def test_publish_and_cycle_rejection(tmp_path):
    import pytest

    from wuxing.tickets import create, load, publish, validate_deps
    t1 = create(tmp_path, title="A")
    create(tmp_path, title="B", deps=[t1["id"]])
    ts = publish(tmp_path)
    assert [t["status"] for t in ts] == ["ready", "ready"]
    assert all(t["status"] == "ready" for t in load(tmp_path))
    # 未知依赖 → 拒绝（可见）
    with pytest.raises(ValueError):
        create(tmp_path, title="C", deps=["T-99"])
    # 环检测：T-3↔T-4 环 → validate/publish 拒绝
    t3 = create(tmp_path, title="D")
    t4 = create(tmp_path, title="E", deps=[t3["id"]])
    from wuxing.tickets import _append
    _append(tmp_path, {"event": "updated", "id": t3["id"],
                       "patch": {"deps": [t4["id"]]}, "ts": 1.0})
    with pytest.raises(ValueError):
        validate_deps(load(tmp_path))
    with pytest.raises(ValueError):
        publish(tmp_path)


def test_publish_only_proposed_and_empty_ids(tmp_path):
    """发布状态机（审查 F2）：仅 proposed→ready；显式空选择不误发；非 proposed 拒绝。"""
    import pytest

    from wuxing.tickets import create, load, publish, update
    create(tmp_path, title="A", goal="a")
    ts = publish(tmp_path)
    assert ts[0]["status"] == "ready"
    update(tmp_path, "T-1", {"status": "done"})
    # 已终态票据不允许被显式发布重置（可见拒绝）
    with pytest.raises(ValueError):
        publish(tmp_path, ["T-1"])
    assert load(tmp_path)[0]["status"] == "done"
    # 显式空选择：不发布任何票（区别于缺省=全部 proposed）
    create(tmp_path, title="B", goal="b")
    ts = publish(tmp_path, [])
    assert [t["status"] for t in ts] == ["done", "proposed"]
    # 缺省：仅 proposed → ready
    ts = publish(tmp_path)
    assert [t["status"] for t in ts] == ["done", "ready"]


def test_reset_failed_ticket_includes_failed_deps_closure(tmp_path):
    """W4.5：重置失败票自动补齐依赖闭包（deps 中 failed/cancelled 递归纳入）。

    现场（A 复跑）：重置 T-2/T-3/T-4 时 deps 指向未激活的 T-1 → 悬空依赖；
    当时靠手工「一并激活 T-1」规避。reset 必须做闭包：
    - failed/cancelled 依赖 → 纳入重置集（否则下游 require_ok_deps 永不满足）；
    - done 依赖 → 外部已完成，不重置（执行期按验收通过处理）。
    """
    from wuxing.tickets import create, load, reset, update

    t1 = create(tmp_path, title="T1")
    t2 = create(tmp_path, title="T2", deps=[t1["id"]])
    t3 = create(tmp_path, title="T3", deps=[t2["id"]])
    update(tmp_path, t1["id"], {"status": "done"})
    update(tmp_path, t2["id"], {"status": "failed"})
    update(tmp_path, t3["id"], {"status": "failed"})
    reset(tmp_path, ids=[t3["id"]])
    st = {t["id"]: t["status"] for t in load(tmp_path)}
    assert st == {"T-1": "done", "T-2": "ready", "T-3": "ready"}


def test_reset_pulls_failed_dep_through_done_target(tmp_path):
    """W4.5：显式重置 done 票（重验）时，其 failed 依赖同样纳入闭包。"""
    from wuxing.tickets import create, load, reset, update

    t1 = create(tmp_path, title="T1")
    t2 = create(tmp_path, title="T2", deps=[t1["id"]])
    update(tmp_path, t1["id"], {"status": "failed"})
    update(tmp_path, t2["id"], {"status": "done"})
    reset(tmp_path, ids=[t2["id"]])
    st = {t["id"]: t["status"] for t in load(tmp_path)}
    assert st == {"T-1": "ready", "T-2": "ready"}


def test_reset_rejects_running_and_proposed(tmp_path):
    """W4.5：running（忙）与 proposed（先过发布状态机）不得重置（可见拒绝）。"""
    import pytest

    from wuxing.tickets import create, reset, update

    t1 = create(tmp_path, title="A")
    t2 = create(tmp_path, title="B")
    update(tmp_path, t2["id"], {"status": "running"})
    with pytest.raises(ValueError):
        reset(tmp_path, ids=[t1["id"]])   # proposed
    with pytest.raises(ValueError):
        reset(tmp_path, ids=[t2["id"]])   # running
    with pytest.raises(ValueError):
        reset(tmp_path, ids=["T-99"])     # 未知 id


def test_reset_default_selects_failed_and_cancelled(tmp_path):
    """W4.5：ids 缺省 = 全部 failed/cancelled；done/proposed 不动。"""
    from wuxing.tickets import create, load, reset, update

    t1 = create(tmp_path, title="A")
    t2 = create(tmp_path, title="B")
    t3 = create(tmp_path, title="C")
    create(tmp_path, title="D")  # T-4 proposed
    update(tmp_path, t1["id"], {"status": "failed"})
    update(tmp_path, t2["id"], {"status": "cancelled"})
    update(tmp_path, t3["id"], {"status": "done"})
    reset(tmp_path)
    st = {t["id"]: t["status"] for t in load(tmp_path)}
    assert st == {"T-1": "ready", "T-2": "ready",
                  "T-3": "done", "T-4": "proposed"}


def test_reset_clears_previous_run_residue(tmp_path):
    """W4.5：重置清理旧轮残留（error/fragment_ids/artifacts）——防错误信息误导。"""
    from wuxing.tickets import create, find, reset, update

    t1 = create(tmp_path, title="A")
    update(tmp_path, t1["id"], {"status": "failed",
                                "error": "F-T1:failed",
                                "fragment_ids": ["F-T1", "F-T1-v"],
                                "artifacts": ["F-T1-result.md"]})
    reset(tmp_path, ids=[t1["id"]])
    t = find(tmp_path, t1["id"])
    assert t["status"] == "ready" and t["error"] == ""
    assert t["fragment_ids"] == [] and t["artifacts"] == []


def test_to_fragments_marks_dependent_exec_require_ok_deps(tmp_path):
    """真测裁决 W3：票据依赖=验收通过才开工——下游 execute 碎片须带 require_ok_deps。

    （上游 verify 返回 needs_confirm / failed / verdict_fail 时下游不开工。）
    """
    from wuxing.tickets import create, to_fragments

    t1 = create(tmp_path, title="A")
    t2 = create(tmp_path, title="B", deps=[t1["id"]])
    by = {f["fragment_id"]: f for f in to_fragments([t1, t2])}
    assert by["F-T2"].get("require_ok_deps") is True
    assert not by["F-T1"].get("require_ok_deps")
    assert not by["F-T2-v"].get("require_ok_deps")
