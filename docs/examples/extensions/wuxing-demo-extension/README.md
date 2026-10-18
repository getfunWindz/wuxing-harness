# wuxing-demo-extension（WUXING 扩展示例包）

entry-points 分发示范：一个**真可安装**的扩展包，安装后被 harness 的入口点发现
（`wuxing.extensions` 组）并被加载——演示三条扩展路径：

| 能力 | API | 行为 |
|---|---|---|
| 提示词段 | `api.add_prompt_segment(text, domains=...)` | 向 execute 域注入一行能力提示 |
| 自定义工具 | `api.register_tool(...)` | `demo_text_stats(path)`：统计工作区内文本文件的行数/词数/字符数（只读；workspace 包含性检查；域白名单 execute） |
| 事件钩子 | `api.on(event, handler)` + `api.log(...)` | `TaskDone` 只读观察，写扩展日志（trace `extension_log`） |

## 安装

在仓库根目录（或任意路径）：

```bash
pip install -e docs/examples/extensions/wuxing-demo-extension
```

安装即注册入口点（无需改配置）：

```bash
python -c "from importlib.metadata import entry_points; \
print([ (e.name, e.value) for e in entry_points(group='wuxing.extensions') ])"
# [('wuxing-demo', 'wuxing_demo_extension')]
```

## 使用与验证

1. 正常启动/使用 harness（任务提交、`wuxing run ...` 或壳）——扩展随引擎装配加载。
2. 执行域任务里可调用 `demo_text_stats`（工具白名单合并后可见）。
3. 任务完成（TaskDone）时扩展日志可见（trace 事件 `extension_log`；报告/诊断可见加载记录 `extension_loaded`）。

```bash
# 快速自检（不装 harness 前置——直接验证入口函数面）
python -c "import wuxing_demo_extension as m; print(callable(m.register))"
```

## 卸载

```bash
pip uninstall wuxing-demo-extension
```

## 开发你自己的扩展

- 入口点组：`wuxing.extensions`；值 = `pkg.module`（模块须暴露 `register(api)`；可选 `pkg.module:attr`）。
- 可用注册面：`register_tool` / `on`（只读 V1；E2 起支持干预钩子）/ `add_prompt_segment` / `register_command`。
- 工具须显式声明 `permission`（缺省全禁 → 拒绝执行）；域白名单经 `domains` 合并。
- 参考：本包 `wuxing_demo_extension/__init__.py`；目录形态扩展（非 pip 分发）见同目录 `audit_hook.py` 与
  `~/.wuxing/extensions/`、`<工作区>/.wuxing/extensions/`。

> ⚠️ 安全边界：扩展 = **进程内完全信任代码**（与 pi/DSH 插件同语义）——只安装可信来源；
> 分发审查指引（校验清单）见仓库文档 `docs/WUXING_扩展机制二期_E2_设计_2026-09-26.md` 与评估报告供应链章节。
