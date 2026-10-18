"""会话计划类型（骨架分期 P1/F-4：自 engine.py 提取——壳/引擎单一来源）。

来源：`wuxing/engine.py`（2026-10-04 迁移，函数体逐字节保持）。
使用方：Engine（设计闸）、壳 manager（提交计划预判）。
"""
import logging

logger = logging.getLogger(__name__)


def session_plan(workdir, session_name: str = "",
                 default_mode: str | None = None) -> dict:
    """公开（壳用）：会话下一次提交的计划类型——设计轮 / 执行（G8-M2）。

    与引擎设计闸单一来源（``Engine._theroad_design_needed`` 调用本函数）：
      非 theroad → execution；phase=ready → execution；地图不可用 / 规格缺 /
      无 ready 票据 → design；地图 + 规格 + ready 票据 → execution。
    ``default_mode=None`` → 从三层生效配置读 ``mode_default``（壳无引擎实例时）。
    """
    from wuxing import design_state
    from wuxing import tickets as _tickets
    from wuxing.map_doc import is_usable
    from wuxing.session_modes import resolve as _resolve
    if default_mode is None:
        try:
            from wuxing.config_contract import effective_config
            default_mode = str(effective_config(workdir)["values"].get(
                "mode_default") or "minimal-standard")
        except Exception:
            default_mode = "minimal-standard"
    mode = str(_resolve(workdir, conversation=str(session_name or ""),
                        default=default_mode).get("mode") or "")
    if mode != "theroad":
        return {"kind": "execution", "mode": mode}
    st = design_state.load(workdir)
    if str(st.get("phase") or "") == "ready":
        return {"kind": "execution", "mode": mode}
    if not is_usable(workdir):
        return {"kind": "design", "mode": mode}
    if not str(st.get("spec_slug") or ""):
        return {"kind": "design", "mode": mode}
    if not any(t.get("status") == "ready" for t in _tickets.load(workdir)):
        return {"kind": "design", "mode": mode}
    return {"kind": "execution", "mode": mode}
