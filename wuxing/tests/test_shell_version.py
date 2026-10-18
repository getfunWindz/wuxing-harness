"""TDD：版本化收口（T6.1）——事件信封 `v` 与 `/api/v1` 前缀同源核对。

设计 §9：事件信封 `v` 版本 + type 命名空间；API `/api/v1` 版本化、加法式演进。
单一事实来源：`wuxing.shell.web.version`（两者一致性由本测试守住）。
"""
from wuxing.shell.web.hub import EventHub


def test_event_envelope_version_matches_api_prefix():
    from wuxing.shell.web.version import API_PREFIX, API_VERSION
    assert API_PREFIX == f"/api/v{API_VERSION}"
    assert EventHub().emit("x")["v"] == API_VERSION


def test_shell_version_single_source():
    from wuxing.shell.web.server import SHELL_VERSION as exposed
    from wuxing.shell.web.version import SHELL_VERSION
    assert exposed == SHELL_VERSION
    assert isinstance(SHELL_VERSION, str) and SHELL_VERSION
