"""TDD（二期批 3）：spec 渲染/解析/落盘/最新查询。"""


def test_render_parse_roundtrip():
    from wuxing.spec_doc import parse, render
    text = render("发布工具", {
        "problem": "现状缺失", "solution": "新增 CLI",
        "stories": ["导出报告", "批量处理"], "decisions": "选 A 方案",
        "testing": "单测 + E2E", "out_of_scope": "移动端", "notes": "后续再议"})
    assert text.startswith("# 发布工具 · WUXING spec")
    for heading in ("## Problem Statement", "## Solution", "## User Stories",
                    "## Implementation Decisions", "## Testing Decisions",
                    "## Out of Scope", "## Further Notes"):
        assert heading in text
    d = parse(text)
    assert d["title"] == "发布工具"
    assert d["sections"]["problem"] == "现状缺失"
    assert "- 导出报告" in d["sections"]["stories"]
    assert d["sections"]["out_of_scope"] == "移动端"
    # 容错：缺段/未知段
    d2 = parse("## Problem Statement\n只有一段\n## Unknown\n忽略")
    assert d2["sections"]["problem"] == "只有一段"
    assert d2["sections"]["solution"] == ""


def test_write_default_slug_and_read_latest(tmp_path):
    import pytest

    from wuxing.spec_doc import latest, read, spec_path, write
    e1 = write(tmp_path, title="A", sections={"problem": "p"})
    assert e1["slug"].startswith("spec-") and len(e1["slug"]) == 18  # spec-YYYYMMDD-HHMM
    assert spec_path(tmp_path, e1["slug"]).is_file()
    assert "## Problem Statement" in read(tmp_path, e1["slug"])
    e2 = write(tmp_path, title="B", slug="my-spec", sections={"problem": "p2"})
    assert e2["slug"] == "my-spec"
    got = latest(tmp_path)
    assert got is not None and got[0] in (e1["slug"], "my-spec")
    # 非法 slug 拒绝
    with pytest.raises(ValueError):
        spec_path(tmp_path, "../evil")
