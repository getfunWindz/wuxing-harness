"""壳 REST/SSE 路由分组（Q1：api.py register_api 拆分）。

每个子模块暴露 ``register(server, ctx)``：定义该组 handler 并注册其路由；
共享依赖与工具见 ``base``（ApiContext/_guard/_session_path/_state_arg）。
"""
