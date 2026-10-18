"""壳（Web UI + 轻量 GUI 双承载）实现子包。

边界纪律（AGENTS.md §2 / 壳设计 §2）：只依赖引擎公开 API
（wuxing.engine / wuxing.events / wuxing.shell.protocol）——禁止 import
引擎内部模块、禁止访问引擎内部属性（tests/test_shell_boundary.py 守卫）。
"""
