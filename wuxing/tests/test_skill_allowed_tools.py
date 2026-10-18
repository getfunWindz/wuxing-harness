"""TDD · A14 allowed-tools Phase 1 声明化（解析/校验/展示；零运行时授权面）。

用户裁决 D2（2026-10-06）：`allowed-tools` frontmatter v1 字段（CC 兼容命名）；
面板/详情展示「依赖工具」；声明工具不在任何域白名单 → warning；运行时零权限变化。
"""
import pathlib


def _mk(root: pathlib.Path, name: str, extra: str = "") -> pathlib.Path:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: 演示技能\n{extra}---\n正文\n",
        encoding="utf-8")
    return d


def test_parse_allowed_tools_normalizes():
    from wuxing.skills import parse_allowed_tools
    assert parse_allowed_tools({}) == []
    assert parse_allowed_tools({"allowed-tools": ""}) == []
    assert parse_allowed_tools({"allowed-tools": "read_file, bash"}) == \
        ["read_file", "bash"]
    assert parse_allowed_tools({"allowed-tools": "[read_file, bash]"}) == \
        ["read_file", "bash"]
    assert parse_allowed_tools(
        {"allowed-tools": "bash, 'read_file', bash"}) == ["bash", "read_file"]
    assert parse_allowed_tools({"allowed-tools": " , "}) == []


def test_index_carries_allowed_tools(tmp_path):
    from wuxing.skills import SkillRegistry
    _mk(tmp_path, "demo-a", "allowed-tools: read_file, bash\n")
    idx = SkillRegistry(user_dir=tmp_path).index()
    assert idx["demo-a"]["allowed_tools"] == ["read_file", "bash"]


def test_empty_allowed_tools_warns(tmp_path):
    from wuxing.skills import validate_skill_fields
    errs, warns = validate_skill_fields(
        {"name": "demo-b", "description": "d", "allowed-tools": ""})
    assert errs == [] and any("allowed-tools" in w for w in warns)
    _errs2, warns2 = validate_skill_fields({"name": "demo-b", "description": "d"})
    assert not any("allowed-tools" in w for w in warns2)  # 未声明 → 无告警


def _engine(tmp_path):
    from wuxing.config import EngineConfig
    from wuxing.engine import Engine
    return Engine(cfg=EngineConfig(llm="mock"), workdir=tmp_path)


def test_engine_exposes_allowed_tools(tmp_path):
    _mk(tmp_path / ".skills", "demo-a", "allowed-tools: read_file, bash\n")
    eng = _engine(tmp_path)
    rows = {r["name"]: r for r in eng.list_skills()}
    assert rows["demo-a"]["allowed_tools"] == ["read_file", "bash"]
    detail = eng.skill_detail("demo-a")
    assert detail["allowed_tools"] == ["read_file", "bash"]
    assert detail["allowed_tools_missing"] == []


def test_missing_tools_flagged_and_mcp_known(tmp_path):
    _mk(tmp_path / ".skills", "demo-c",
        "allowed-tools: read_file, not_a_real_tool, mcp:github\n")
    eng = _engine(tmp_path)
    detail = eng.skill_detail("demo-c")
    assert detail["allowed_tools_missing"] == ["not_a_real_tool"]
