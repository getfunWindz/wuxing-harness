"""任务产物聚合（骨架分期 P5：自 engine.py 提取——中性共享模块）。

来源：`wuxing/engine.py`（2026-10-06 迁移；函数体逐字节保持）。
理由：`_run_design_round` 迁 `engine_session` 后仍需本函数（mixin 禁 import engine）——
落中性模块供 engine / engine_session 共用（F-4 共享工具先例）。
"""


def result_artifacts(units) -> list:
    """任务产物清单 = 契约产物 + 单元真实交付物（去重保序）。

    2026-10-01 真机修复（用户反馈「只生产了报告没有生成网站本身」）：
    模型用 write_file 写出真实交付物（index.html/src/* 等），但此前只把
    write_artifact 的契约文件计入 TaskResult.artifacts——UI/报告只看到
    F-*-result.md 等报告文件。现把单元 deliverables（写工具真实产物）一并
    汇总（同一路径保留首个——契约产物优先）。
    """
    from wuxing.protocols import Artifact
    out: list = []
    seen: set[str] = set()
    for u in units or []:
        for a in (getattr(u, "artifacts", None) or []):
            p = str(getattr(a, "path", "") or "")
            if p and p not in seen:
                seen.add(p)
                out.append(a)
    for u in units or []:
        for p in (getattr(u, "deliverables", None) or []):
            text = str(p or "")
            if text and text not in seen:
                seen.add(text)
                out.append(Artifact(path=text, kind="",
                                    producer_unit=str(getattr(u, "unit_id", "") or "")))
    return out
