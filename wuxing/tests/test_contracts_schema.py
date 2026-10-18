"""contracts.validate_schema 语义特性测试（2026-10-03 裁定固定）。

修复背景：docstring 曾称「无 jsonschema → True（不阻断）」——那是初始覆盖语义
（28c0b32：JSON dict 时 schema 结果覆盖关键词判定）时代的表述，True 意为
「不否决关键词」；现为 OR 语义（contract_check：passed = passed or
validate_schema(...)），False 已不否决其他判定路径，仅表示「本路径不贡献
通过」。若缺失库时返回 True，等于未校验即放行（fail-open）——与机制裁决
原则相悖。本文件固定该裁定。
"""
import sys

from wuxing.contracts import validate_schema

_SCHEMA = {"type": "object", "required": ["plan"]}


def test_empty_schema_passes():
    # 无 schema 可校验 → 跳过（不阻断）
    assert validate_schema({"anything": 1}, {}) is True


def test_valid_data_passes():
    assert validate_schema({"plan": {"steps": []}}, _SCHEMA) is True


def test_invalid_data_fails():
    assert validate_schema({"foo": "bar"}, _SCHEMA) is False


def test_missing_jsonschema_does_not_grant_pass(monkeypatch):
    # jsonschema 不可用（精简环境）→ 不虚发放行（不贡献通过）
    monkeypatch.setitem(sys.modules, "jsonschema", None)
    assert validate_schema({"plan": {}}, _SCHEMA) is False
