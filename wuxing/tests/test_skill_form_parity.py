"""A9（v43-⑦）：壳技能安装表单预校验与引擎同规守卫（常量级 parity——防双写漂移）。

规则单一事实源 = `wuxing/skills.py`（`install_skill` / `validate_skill_fields`）；
壳侧镜像实现 = `apps/shell/web/src/views/skill-form.ts`（纯函数，前端测试覆盖行为）。
本文件只守「最容易漂移的常量与正则」——语义行为由两侧各自测试锁定。
"""
import pathlib
import re

from wuxing.skills import _NAME_RE, DESCRIPTION_MAX, NAME_MAX

FORM_TS = (pathlib.Path(__file__).resolve().parents[2]
           / "apps" / "shell" / "web" / "src" / "views" / "skill-form.ts")


def _src() -> str:
    return FORM_TS.read_text(encoding="utf-8")


def test_shell_skill_form_constants_match_engine():
    src = _src()
    assert f"SKILL_NAME_MAX = {NAME_MAX}" in src, "壳侧 SKILL_NAME_MAX 与引擎 NAME_MAX 漂移"
    assert f"SKILL_DESC_MAX = {DESCRIPTION_MAX}" in src, \
        "壳侧 SKILL_DESC_MAX 与引擎 DESCRIPTION_MAX 漂移"


def test_shell_skill_form_name_regex_matches_engine():
    m = re.search(r"SKILL_NAME_RE = /(.+?)/;", _src())
    assert m, "skill-form.ts 未找到 SKILL_NAME_RE 字面量"
    assert m.group(1) == _NAME_RE.pattern, \
        f"壳侧名字正则与引擎漂移：{m.group(1)!r} != {_NAME_RE.pattern!r}"
