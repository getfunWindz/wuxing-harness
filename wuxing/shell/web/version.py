"""壳版本常量（单一事实来源——T6.1 收口）。

`API_VERSION` 同时决定 REST 前缀（`/api/v{n}`）与事件信封 `v` 字段；
两者若需语义独立演进，必须在此显式拆分并同步测试（test_shell_version.py）。
"""
API_VERSION = 1
API_PREFIX = f"/api/v{API_VERSION}"
SHELL_VERSION = "p1"
