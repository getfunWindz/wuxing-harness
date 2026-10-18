"""TDD（双模式批 3 · Task 2）：WUXING.md——模板/解析/写/哈希/可用/摘要。"""


def test_template_and_write_parse_roundtrip(tmp_path):
    from wuxing.map_doc import (
        file_hash,
        is_usable,
        map_path,
        parse,
        read,
        write_sections,
    )
    assert not is_usable(tmp_path)
    assert read(tmp_path) is None
    text = write_sections(tmp_path, project="演示项目",
                          destination="发布 v1 可用版本",
                          route="- [ ] 实现核心模块\n- [x] 建仓库",
                          decisions="2026-09-24 · 用 Python · 团队熟悉 · 设计 §5",
                          fog="部署方式未定", out_of_scope="移动端不做")
    assert "由 WUXING 维护" in text
    assert map_path(tmp_path).is_file()
    d = parse(text)
    assert d["project"] == "演示项目"
    assert d["destination"] == "发布 v1 可用版本"
    assert d["route"][0].startswith("- [ ] 实现核心模块")
    assert d["decisions"] == ["2026-09-24 · 用 Python · 团队熟悉 · 设计 §5"]
    assert d["fog"] == ["部署方式未定"] and d["out_of_scope"] == ["移动端不做"]
    assert is_usable(tmp_path) and len(file_hash(map_path(tmp_path))) == 64
    # decisions append（不覆盖历史）
    write_sections(tmp_path, decisions="2026-09-25 · 加缓存 · 性能 · 评审")
    d2 = parse(map_path(tmp_path).read_text(encoding="utf-8"))
    assert len(d2["decisions"]) == 2
    # 段替换（route 覆盖）
    write_sections(tmp_path, route="- [x] 实现核心模块")
    d3 = parse(map_path(tmp_path).read_text(encoding="utf-8"))
    assert d3["route"] == ["- [x] 实现核心模块"]
    # 空写不破坏（只重渲染）
    write_sections(tmp_path)
    assert parse(map_path(tmp_path).read_text(encoding="utf-8"))["destination"] \
        == "发布 v1 可用版本"


def test_parse_tolerates_missing_sections_and_digest(tmp_path):
    from wuxing.map_doc import digest, is_usable, parse, write_sections
    assert parse("随便一段文字")["destination"] == ""
    assert not is_usable(tmp_path)
    write_sections(tmp_path, project="P", destination="D" * 10,
                   route="\n".join(f"- [ ] 步骤{i}" for i in range(30)))
    dg = digest(tmp_path, max_chars=200)
    assert len(dg) <= 260 and "目的地" in dg and "步骤0" in dg
    assert is_usable(tmp_path)


def test_parse_decisions_structured_and_legacy(tmp_path):
    from wuxing.map_doc import parse_decisions
    lines = [
        "- [D-1] 2026-09-25 决策：采用 X｜理由：简单｜上游：—｜取代：—｜来源：Q-1",
        "- [D-2] 2026-09-25 决策：改用 Y｜理由：性能｜上游：D-1｜取代：D-1｜来源：Q-3",
        "旧自由文本决策行",
    ]
    ds = parse_decisions(lines)
    assert ds[0]["id"] == "D-1" and ds[0]["text"] == "采用 X"
    assert ds[0]["why"] == "简单" and ds[0]["source"] == "Q-1"
    assert ds[0]["upstream"] == [] and ds[0]["supersedes"] == []
    assert ds[1]["upstream"] == ["D-1"] and ds[1]["supersedes"] == ["D-1"]
    assert ds[2]["id"] == "" and ds[2]["text"] == "旧自由文本决策行"


def test_heads_and_branch_rollback(tmp_path):
    """回滚分岔：D-3 取代 D-2 且上游回指 D-1 → heads=[D-3]，分支=D-3→D-1。"""
    from wuxing.map_doc import branch, heads, parse_decisions
    ds = parse_decisions([
        "- [D-1] 2026-09-25 决策：A｜理由：—｜上游：—｜取代：—｜来源：Q-1",
        "- [D-2] 2026-09-25 决策：B｜理由：—｜上游：D-1｜取代：—｜来源：Q-2",
        "- [D-3] 2026-09-25 决策：C｜理由：—｜上游：D-1｜取代：D-2｜来源：Q-3",
    ])
    assert heads(ds) == ["D-3"]
    assert branch(ds, "D-3") == ["D-3", "D-1"]


def test_append_decision_allocates_ids_and_appends(tmp_path):
    from wuxing.map_doc import append_decision, parse_decisions, read
    e1 = append_decision(tmp_path, text="采用 A", why="稳", source="Q-1")
    e2 = append_decision(tmp_path, text="采用 B", upstream=e1["id"], source="Q-2")
    assert e1["id"] == "D-1" and e2["id"] == "D-2"
    ds = parse_decisions((read(tmp_path) or {}).get("decisions") or [])
    assert [d["id"] for d in ds] == ["D-1", "D-2"]
    assert ds[1]["upstream"] == ["D-1"]


def test_write_and_parse_split_br_route_lines(tmp_path):
    """真测观察：路线条目中的 <br> 归一为多行（防 digest/简报单行排版）。"""
    from wuxing.map_doc import digest, parse, write_sections
    write_sections(tmp_path, project="演示",
                   route="1. 侦察<br>2. 拷问<br/>3. 地图<br />4. 规格")
    d = parse((tmp_path / "WUXING.md").read_text(encoding="utf-8"))
    assert d["route"] == ["1. 侦察", "2. 拷问", "3. 地图", "4. 规格"]
    dg = digest(tmp_path)
    assert "<br" not in dg.lower()
    assert "1. 侦察" in dg and "4. 规格" in dg


def test_write_splits_br_in_fog_and_out_of_scope(tmp_path):
    from wuxing.map_doc import parse, write_sections
    write_sections(tmp_path, project="演示", fog="a<br>b", out_of_scope="x<br/>y")
    d = parse((tmp_path / "WUXING.md").read_text(encoding="utf-8"))
    assert d["fog"] == ["a", "b"]
    assert d["out_of_scope"] == ["x", "y"]


def test_parse_normalizes_br_in_preexisting_file(tmp_path):
    """读侧归一：已写入的单行 <br> 地图（旧文件）直接可正确解析/展示。"""
    from wuxing.map_doc import parse
    (tmp_path / "WUXING.md").write_text(
        "# 演示 · WUXING 地图\n\n## 路线\n\n1. A<br>2. B\n", encoding="utf-8")
    d = parse((tmp_path / "WUXING.md").read_text(encoding="utf-8"))
    assert d["route"] == ["1. A", "2. B"]
