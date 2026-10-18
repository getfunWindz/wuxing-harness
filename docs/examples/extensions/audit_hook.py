"""示例扩展（E0-A 一期）：审计钩子 + ext_line_count 工具。

安装（三选一）：
  1. 复制本文件到 ~/.wuxing/extensions/（用户级）
  2. 复制到 <工作区>/.wuxing/extensions/（项目级）
  3. 配置 extension_dirs 指向本文件所在目录（相对路径按工作区解析）

扩展 = 进程内完全信任代码——只加载可信来源。工具须显式声明 permission
（缺省全禁 → Registry 默认拒绝执行）；钩子 V1 只读（返回值忽略）。
"""


def register(api):
    workdir = api.workdir.resolve()

    # ── 事件钩子（只读观察）：关键事件写扩展日志（trace: extension_log）──
    def _audit(event):
        name = type(event).__name__
        detail = getattr(event, "unit_id", "") or getattr(event, "status", "")
        api.log(f"{name} {detail}".strip())

    for _evt in ("UnitStarted", "UnitDone", "TaskDone"):
        api.on(_evt, _audit)

    # ── 自定义工具（域白名单合并：仅执行域可见；显式声明只读权限）──
    def _line_count(path=""):
        p = (workdir / str(path)).resolve()
        if p != workdir and workdir not in p.parents:
            return {"error": f"outside workspace: {path}"}
        text = p.read_text(encoding="utf-8")
        return {"path": str(path), "lines": len(text.splitlines())}

    api.register_tool(
        name="ext_line_count",
        description="统计工作区内文本文件的行数（示例扩展工具）",
        parameters={"type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"]},
        execute=_line_count,
        domains=("execute",),
        permission={"read": True},
    )
