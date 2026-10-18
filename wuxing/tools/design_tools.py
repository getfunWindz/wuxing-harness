"""循迹设计工具（双模式批 3 · 设计 §5.2/§5.4）：write_map——受控写 WUXING.md。

纪律：仅 design 域白名单可及（引擎级注册——同 delegate 路径）；用户确认由设计
提示词纪律 + 壳「交给执行」软门承载（v1 不上逐工具确认机制——防臃肿）。
"""
import time

from wuxing.protocols import Tool


class WriteMapTool(Tool):
    def __init__(self, ws):
        self._ws = ws

    def name(self): return "write_map"

    def description(self):
        return ("写入/更新工作区地图 WUXING.md（目的地/路线/决策记录/未定/范围外；"
                "仅循迹设计会话、用户确认后调用；决策记录 append。"
                "注意：decisions 参数仅用于首次建档/历史迁移——运行期决策请用【决策】块，"
                "由引擎关闭票据并入图）")

    def input_schema(self): return {"type": "object", "properties": {
        "project": {"type": "string"},
        "destination": {"type": "string"},
        "route": {"type": "string"},
        "decisions": {"type": "string"},
        "fog": {"type": "string"},
        "out_of_scope": {"type": "string"}}}

    def permission(self):
        return {"read": False, "write": True, "execute": False,
                "network": False, "destructive": False}

    def execute(self, project="", destination=None, route=None, decisions=None,
                fog=None, out_of_scope=None, **kw):
        from wuxing import design_state, map_doc
        from wuxing.protocols import ToolResult
        try:
            map_doc.write_sections(
                self._ws.root, project=str(project or ""),
                destination=destination, route=route, decisions=decisions,
                fog=fog, out_of_scope=out_of_scope)
            h = map_doc.file_hash(map_doc.map_path(self._ws.root))
            design_state.save(self._ws.root, {
                "phase": "map", "map_path": map_doc.MAP_FILENAME,
                "map_hash": h})
            return ToolResult(
                status="ok", tool_name=self.name(),
                content=f"地图已写入 {map_doc.MAP_FILENAME}（hash {h[:12]}）")
        except OSError as e:
            return ToolResult(status="error", tool_name=self.name(),
                              error=str(e))


class WriteSpecTool(Tool):
    """写工作区规格（.wuxing/specs/<slug>.md；受控七段）。

    纪律：仅 design 域白名单可及（引擎级注册——同 write_map）；用户确认由设计
    提示词纪律承载（软编排——机制不硬拦）。
    """

    def __init__(self, ws):
        self._ws = ws

    def name(self): return "write_spec"

    def description(self):
        return ("写入工作区规格 .wuxing/specs/<slug>.md（七段：Problem/Solution/"
                "User Stories/Implementation Decisions/Testing Decisions/"
                "Out of Scope/Further Notes）；票据全关且用户确认后调用"
                "（未关闭时仍写入但携带警告并记入 drift——软口径）；"
                "不写文件路径与代码片段（原型片段除外）")

    def input_schema(self):
        return {"type": "object", "properties": {
            "title": {"type": "string"}, "slug": {"type": "string"},
            "problem": {"type": "string"}, "solution": {"type": "string"},
            "stories": {"type": "string"}, "decisions": {"type": "string"},
            "testing": {"type": "string"}, "out_of_scope": {"type": "string"},
            "notes": {"type": "string"}}}

    def permission(self):
        return {"read": False, "write": True, "execute": False,
                "network": False, "destructive": False}

    def execute(self, title="", slug="", problem="", solution="", stories="",
                decisions="", testing="", out_of_scope="", notes="", **kw):
        from wuxing import design_state, spec_doc
        from wuxing.protocols import ToolResult
        try:
            st = design_state.load(self._ws.root)
            open_tks = design_state.tickets(st)
            entry = spec_doc.write(
                self._ws.root, title=str(title or "未命名"), slug=str(slug or ""),
                sections={"problem": problem, "solution": solution,
                          "stories": stories, "decisions": decisions,
                          "testing": testing, "out_of_scope": out_of_scope,
                          "notes": notes})
            patch = {
                "spec_path": f".wuxing/specs/{entry['slug']}.md",
                "spec_slug": entry["slug"], "spec_hash": entry["hash"]}
            warn = ""
            if open_tks:
                # C5：带未关闭决策票合成规格 → 软提示（不硬拦；警告 + drift 可见）
                ids = "、".join(str(t.get("id")) for t in open_tks)
                patch["drift"] = design_state.merge_drift(st.get("drift"), [{
                    "round": int(st.get("round") or 0),
                    "kind": "spec-with-open-tickets", "id": ids,
                    "detail": f"规格合成时存在未关闭决策票：{ids}",
                    "ts": round(time.time(), 3)}])
                warn = (f"（警告：存在 {len(open_tks)} 张未关闭决策票：{ids}"
                        "——建议先关闭（【决策】块）再合成规格；"
                        "已记入设计态 drift）")
            design_state.save(self._ws.root, patch)
            return ToolResult(status="ok", tool_name=self.name(),
                              content=f"规格已写入 .wuxing/specs/"
                                      f"{entry['slug']}.md" + warn)
        except (OSError, ValueError) as e:
            return ToolResult(status="error", tool_name=self.name(),
                              error=str(e))


class UnclaimTicketTool(Tool):
    """释放票据认领（G8）：仅循迹设计域；用户确认陈旧认领后调用。

    陈旧认领视图经设计轮上下文 ``[票据认领]`` 块注入；agent 向用户确认后
    调用本工具释放（手动释放通道另经 CLI/接口保留）。
    """

    def __init__(self, ws):
        self._ws = ws

    def name(self): return "unclaim_ticket"

    def description(self):
        return ("释放实施票据的认领（陈旧认领经用户确认后调用；"
                "参数 id 如 T-2，reason 记录原因）")

    def input_schema(self):
        return {"type": "object", "properties": {
            "id": {"type": "string"},
            "reason": {"type": "string"}},
            "required": ["id"]}

    def permission(self):
        return {"read": True, "write": True, "execute": False,
                "network": False, "destructive": False}

    def execute(self, id="", reason="", **kw):
        from wuxing import tickets
        from wuxing.protocols import ToolResult
        tid = str(id or "").strip()
        if not tid:
            return ToolResult(status="error", tool_name=self.name(),
                              error="缺少票据 id")
        t = tickets.find(self._ws.root, tid)
        if t is None:
            return ToolResult(status="error", tool_name=self.name(),
                              error=f"未知票据：{tid}")
        if not t.get("claimed_by"):
            return ToolResult(status="ok", tool_name=self.name(),
                              content=f"票据 {tid} 无活动认领（幂等）")
        tickets.unclaim(self._ws.root, tid, by="design-agent",
                        reason=str(reason or "用户确认清除陈旧认领"))
        return ToolResult(status="ok", tool_name=self.name(),
                          content=f"已释放票据 {tid} 的认领")
