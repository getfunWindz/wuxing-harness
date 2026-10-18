import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))


@pytest.fixture(autouse=True)
def _disable_skill_evolution(monkeypatch):
    """技能自进化含额外 LLM 调用（默认开）——测试默认禁用（专项测试自行覆盖）。

    仅测试夹具；真实运行默认开（用户裁决 2026-09-12）。
    """
    from wuxing.engine import Engine
    monkeypatch.setattr(Engine, "_skill_evolution_hook",
                        lambda self, *_a, **_k: None)


@pytest.fixture(autouse=True)
def _isolate_user_config(tmp_path, monkeypatch):
    """隔离真实用户配置（~/.wuxing/config.jsonc）——测试不得受用户设置影响。

    背景（2026-09-14 实证）：用户在设置中心开启 brain_enabled / use_real_shape
    后，引擎测试因读取真实用户配置而大面积行为漂移（18 项失败）。
    需要全局层的测试自行传 global_config_dir。
    """
    import wuxing.config_contract as cc
    import wuxing.config_loader as cl
    import wuxing.credentials as creds
    isolated = tmp_path / "_no_user_config"
    monkeypatch.setattr(cl, "_global_config_dir", lambda: isolated)
    monkeypatch.setattr(cc, "user_config_path", lambda: isolated / "config.jsonc")
    monkeypatch.setattr(creds, "credentials_path",
                        lambda: isolated / "credentials.json")
    import wuxing.skill_state as st
    monkeypatch.setattr(st, "state_path",
                        lambda: isolated / "state" / "skills" / "disabled.json")
    monkeypatch.setattr(st, "pinned_path",
                        lambda: isolated / "state" / "skills" / "pinned.json")
    monkeypatch.setattr(st, "legacy_state_path",
                        lambda: isolated / "skills-disabled.json")
    monkeypatch.setattr(st, "legacy_pinned_path",
                        lambda: isolated / "skills-pinned.json")


@pytest.fixture(autouse=True)
def _isolate_user_extensions(tmp_path, monkeypatch):
    """E0-A：隔离真实用户扩展目录（~/.wuxing/extensions）——本机扩展不得影响测试。"""
    import wuxing.extensions as ext
    monkeypatch.setattr(ext, "user_extensions_dir",
                        lambda: tmp_path / "_no_user_extensions")
