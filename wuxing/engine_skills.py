"""Engine 技能子系统（骨架分期 P2/F-3a：自 engine.py 提取的方法组）。

来源：`wuxing/engine.py`（2026-10-04 迁移；方法体逐字节保持）。
理由：F-3 巨型文件分期——技能面落隔离模块（S-2 mixin 裁定）；engine 只做类基接线。
依赖：经 `self` 访问引擎状态（cfg/skills/llm/trace）；**不得 import engine**（守卫）。
"""
import logging
import pathlib
import time

logger = logging.getLogger(__name__)


class EngineSkillsMixin:
    @staticmethod
    def _known_tool_names() -> set:
        """A14：全域白名单并集（静态面——DEFAULT_DOMAINS + 设计域）。"""
        from wuxing.domains.defaults import DEFAULT_DOMAINS, DESIGN_DOMAIN
        names: set = set()
        for d in list(DEFAULT_DOMAINS.values()) + [DESIGN_DOMAIN]:
            names.update(str(t) for t in (getattr(d, "tool_whitelist", ()) or ()))
        return names

    def _allowed_tools_missing(self, tools: list) -> list:
        """A14：声明工具中不在任何域白名单者（展示警示数据；零授权面）。"""
        known = self._known_tool_names()
        out = []
        for t in tools or ():
            name = str(t)
            if name in known:
                continue
            if name.startswith("mcp:") and "mcp:*" in known:
                continue
            out.append(name)
        return out

    def list_skills(self) -> list[dict]:
        """公开契约（UI 重构阶段 2）：已装载技能清单——名称/描述/层级。

        壳用它做技能快捷选择；不暴露技能内部路径与脚本细节。
        """
        try:
            index = self.skills.index() or {}
        except Exception:
            return []
        out = []
        from wuxing.skill_state import load_disabled
        disabled = load_disabled()
        for name, info in sorted(index.items()):
            out.append({
                "name": name,
                "description": str((info or {}).get("description", "")),
                "level": str((info or {}).get("level", "")),
                "enabled": name not in disabled,
                # E2-1（B5）：调用策略——壳选择器按 user_invocable 过滤
                "model_invocable": bool((info or {}).get("model_invocable", True)),
                "user_invocable": bool((info or {}).get("user_invocable", True)),
                "allowed_tools": list((info or {}).get("allowed_tools") or []),
            })
        return out

    # ---- 技能管理（阶段 5 · T5.1——壳管理面公开契约） ----

    def skill_detail(self, name: str) -> dict | None:
        """技能详情（SKILL.md 全文 + scripts + builtin 标记）；不存在/破损 → None。"""
        nm = str(name)
        try:
            detail = self.skills.get_detail(nm)
            if detail is None:
                return None
            detail["builtin"] = nm in self._builtin_skill_names()
            info = self.skills.index().get(nm) or {}
            detail["level"] = str(info.get("level", ""))
            # E2-1（B5）：调用策略随详情暴露（选择器/管理面消费）
            detail["model_invocable"] = bool(info.get("model_invocable", True))
            detail["user_invocable"] = bool(info.get("user_invocable", True))
            _tools = [str(t) for t in (info.get("allowed_tools") or [])]
            detail["allowed_tools"] = _tools
            # A14：声明化清点（不在任何域白名单 → 展示面警示；零授权面）
            detail["allowed_tools_missing"] = self._allowed_tools_missing(_tools)
            from wuxing.skill_state import load_disabled
            detail["enabled"] = nm not in load_disabled()
            return detail
        except Exception:
            # 技能详情组装失败 → None（展示面容错：缺失即不可见）
            return None

    def install_skill(self, name: str, description: str, content: str,
                      scripts: dict | None = None) -> dict:
        """安装技能到用户级目录（调用方负责用户确认——人工介入哲学）。"""
        from wuxing.skills import install_skill as _install
        path = _install(self.skills.user_dir, str(name), str(description),
                        str(content), scripts)
        return {"ok": True, "name": str(name), "path": str(path)}

    def _builtin_skill_names(self) -> set:
        out: set = set()
        try:
            b = getattr(self.skills, "builtin_dir", None)
            if b is not None and pathlib.Path(b).is_dir():
                out = {p.name for p in pathlib.Path(b).iterdir() if p.is_dir()}
        except OSError as exc:
            logger.debug("内置技能目录读取失败（不阻断）：%s", exc)
        return out

    def remove_skill(self, name: str) -> dict:
        """卸载用户级技能（内置只读；不存在明确报错）。"""
        nm = str(name or "").strip()
        if not nm or nm in (".", "..") or "/" in nm or "\\" in nm:
            raise ValueError(f"非法技能名：{name!r}")
        if nm in self._builtin_skill_names():
            raise ValueError(f"内置技能不可卸载：{nm}")
        target = pathlib.Path(self.skills.user_dir) / nm
        if not target.is_dir():
            raise ValueError(f"技能不存在：{nm}")
        import shutil
        shutil.rmtree(target)
        return {"ok": True, "name": nm}

    def set_skill_enabled(self, name: str, enabled: bool) -> dict:
        """技能启停（M7 #5）：停用后不出现在索引/选择器，load_skill 拒绝。

        内置技能只读（不可停用）；未知/非法技能名明确报错（失败可见）。
        """
        nm = str(name or "").strip()
        if not nm or nm in (".", "..") or "/" in nm or "\\" in nm:
            raise ValueError(f"非法技能名：{name!r}")
        if nm in self._builtin_skill_names():
            raise ValueError(f"内置技能不可停用：{nm}")
        if nm not in (self.skills.index() or {}):
            raise ValueError(f"技能不存在：{nm}")
        from wuxing.skill_state import load_disabled, save_disabled
        disabled = load_disabled()
        if enabled:
            disabled.discard(nm)
        else:
            disabled.add(nm)
        save_disabled(disabled)
        return {"ok": True, "name": nm, "enabled": bool(enabled)}

    def discover_skills(self, goal: str, constraints: str = "",
                        max_results: int = 5) -> dict:
        """SkillRadar 在线发现（失败结构化返回——不挂引擎）。"""
        from wuxing.skills import SkillRadarClient
        try:
            items = SkillRadarClient().discover(str(goal), str(constraints),
                                                max_results=max_results)
            return {"ok": True, "items": items}
        except Exception as exc:  # 网络/解析失败不挂引擎
            return {"ok": False, "items": [],
                    "error": f"{type(exc).__name__}: {exc}"[:200]}

    def skill_near_duplicates(self) -> dict:
        """技能近义报告（只读；用户级目录）——壳维护面后续消费留缝（B 面）。

        结构化失败（异常 → error 字段置明；不挂引擎）。
        """
        from wuxing.skill_curator import NEAR_BODY_J, NEAR_NAME_J, near_duplicate_report
        empty = {"skills_total": 0,
                 "thresholds": {"name": NEAR_NAME_J, "body": NEAR_BODY_J},
                 "pairs": [], "clusters": [], "singletons": [],
                 "now": 0.0, "error": ""}
        sdir = getattr(self.skills, "user_dir", None)
        if not sdir:
            return empty
        try:
            out = near_duplicate_report(sdir)
            out["error"] = ""
            return out
        except Exception as exc:
            empty["error"] = f"{type(exc).__name__}: {exc}"[:200]
            return empty

    def _skill_evolution_hook(self, task_text: str, units: list, status: str,
                              metrics: dict | None = None) -> None:
        """技能自进化（用户裁决 2026-09-12——默认开）：高效任务自评审沉淀 skill。

        机械证据闸（全 ok + done）→ LLM 自评审 → 沉淀（失败静默——技能是
        优化不是生命线）；成功沉淀 → trace `skill_evolved`。
        E0-6：评审调用计入辅助账目（失败路径也记——已发生成本）；
        metrics 传入时尾差合并（评审在 _collect_metrics 之后运行）。
        """
        if getattr(self, "isolated", False):
            return  # G4：隔离装配无技能面
        if not getattr(self.cfg, "skill_evolution_enabled", True):
            return
        if self.skills is None:
            return
        res: dict = {}
        try:
            from wuxing.skill_evolution import review_and_distill
            from wuxing.usage_tracker import UsageTracker
            _ut = UsageTracker(self.llm)
            _t0 = time.perf_counter()
            _snap = _ut.snapshot()
            try:
                res = review_and_distill(task_text, units, status, self.llm,
                                         skills_dir=self.skills.user_dir)
            finally:
                self._record_aux_call("skill_review", _ut.since(_snap),
                                      t0=_t0)
        except Exception:
            logger.debug("技能自进化评审异常（优化非生命线——静默）")
        if metrics is not None:
            try:
                self._merge_aux_into_metrics(metrics)
            except Exception as exc:
                logger.debug("辅助账目合并失败（观测不阻断）：%s", exc)
        if res.get("installed"):
            # C2：收益台账（触发数——与 trace 同源双写）
            from wuxing.skill_ledger import record_event
            record_event(self.skills.user_dir, "evolved", res.get("name", ""))
            if self.trace is not None:
                try:
                    self.trace.log("skill_evolved", "", "",
                                   name=res.get("name", ""))
                except Exception as exc:
                    logger.debug("技能沉淀事件记录失败（观测不阻断）：%s", exc)
        elif res.get("duplicate_of"):
            # 近义查重命中：技能未沉淀——留审计痕（台账 + trace 双写）
            from wuxing.skill_ledger import record_event
            record_event(self.skills.user_dir, "evolve_skipped",
                         res.get("name", ""),
                         source=str(res.get("duplicate_of", "")))
            if self.trace is not None:
                try:
                    self.trace.log("skill_evolve_skipped", "", "",
                                   name=res.get("name", ""),
                                   duplicate_of=str(res.get("duplicate_of", "")))
                except Exception as exc:
                    logger.debug("技能近义跳过事件记录失败（观测不阻断）：%s", exc)

